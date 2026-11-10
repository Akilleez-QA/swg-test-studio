#!/usr/bin/env python3
"""Run the ELF64 protocol peer in an existing, labelled Stage 5 fixture.

No images, databases, privileges, client patches or arbitrary game commands.
Bot identities and evidence are retained in the private fixture directory.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import secrets
import subprocess
import sys
import threading
import time

from prepare_client_fixture_schema import REPO, target_root, run
from disposable_database import validate
from instance_schema_upgrade import sql_script
from prepare_stage5_client_fixture64 import inspect_project
from studio_tool_bundle import TOOLS_ROOT
import server_profile
sys.path.insert(0, str(TOOLS_ROOT / 'manage'))
from service import operation_lock


def identity(value):
    if (value.get('schema_version') != 1 or
            not re.fullmatch(r'capbot_[a-f0-9]{7}', value.get('account', '')) or
            not re.fullmatch(r'Cap[a-z]{12}', value.get('character', ''))):
        raise ValueError('Invalid dedicated bot identity')
    for field, limit in (('player', 19), ('station', 10), ('ship', 19)):
        if field in value and not re.fullmatch(r'[1-9][0-9]{0,' + str(limit-1) + '}', value[field]):
            raise ValueError('Invalid dedicated bot ' + field)
    return value


def local_auth(text):
    section = ''
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1]
        elif section == 'LoginServer' and '=' in line and not line.startswith(('#', ';', '//')):
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip()
    return values.get('doSessionLogin') == 'false' and values.get('validateStationKey') == 'false'


def expected_prompt(page, prompt):
    return page.get('name') == 'Script.messageBox' and any(
        p.get('widget') == 'Prompt.lblPrompt' and p.get('property') == 'Text' and p.get('value') == prompt
        for p in page.get('properties', []))


def authored_shuttle_room(source_family, destination_family):
    # Gamma's original return uses FROM_ORD_SPACE_TO_STATION_CELL, not the
    # general station entrance in zone_transition. Displayed hangar numbering
    # does not identify the server's internal cell name.
    rooms = {('npe_space_station', 'npe_space_dungeon'): 'cave_entrance',
             ('npe_space_dungeon', 'npe_space_station'): 'hangarbay1'}
    if (source_family, destination_family) not in rooms:
        raise ValueError('Unsupported authored shuttle direction')
    return rooms[source_family, destination_family]


def fixture(folder, allow_stopped_role=None):
    folder = folder.resolve(strict=True)
    root, _, volume = target_root(folder.parent)
    if not re.fullmatch(r'client-[a-f0-9]{12}', folder.name):
        raise ValueError('Expected a prepared private client fixture')
    proof = json.loads((folder / 'schema-report.json').read_text())
    report = json.loads((folder / 'runtime/report.json').read_text())
    stage = json.loads((folder / 'runtime/stage5-report.json').read_text())
    schema = 'WGC_' + folder.name[7:].upper()
    if (not proof.get('passed') or proof.get('schema') != schema or
            report.get('schema') != schema or report.get('project') != root.name or
            stage.get('stage') != 5 or stage.get('schema') != schema or stage.get('project') != root.name):
        raise ValueError('Matching verified Stage 5 schema required')
    services = {r['Config']['Labels']['com.docker.compose.service']: r for r in inspect_project(root.name)}
    validate(services['oracle'], root, volume)
    release = json.loads((REPO / server_profile.active().deployment / 'instance-release.json').read_text())
    for role, pin in release['roles'].items():
        row = services[role]
        stopped_fault_role = (allow_stopped_role in ('taskmanager','game','planet') and role == allow_stopped_role and
                              row['State']['Status'] == 'exited' and not row['State']['Running'])
        if ((not row['State']['Running'] and not stopped_fault_role) or row['Image'] != pin['image_id'] or
                row['Config']['Labels'].get('whitengold.test.client') != schema):
            raise ValueError('Fixture role is stopped, unlabelled or has a different image: ' + role)
    cfg = (folder / 'runtime/runtime.cfg').read_text()
    if not local_auth(cfg):
        raise ValueError('Driver requires the fixture\'s existing local authentication mode')
    return root.name, schema, services


def sql(project, schema, select):
    # Internal read-only queries only. Never accept SQL through the CLI.
    result = subprocess.run(['docker', 'exec', '-i', '--user', 'oracle', project + '-oracle-1',
                             'sqlplus', '-s', '/nolog'],
                            input=sql_script('set transaction read only;\n' + select + '\nrollback;'),
                            text=True, capture_output=True, timeout=60)
    if result.returncode or re.search(r'(^|\n)(ORA-|SP2-)', result.stdout + result.stderr):
        raise RuntimeError('Read-only fixture query failed')
    return [json.loads(s) for s in result.stdout.splitlines() if s.startswith('{')]


def saved_query(schema, player, zone_instances=True):
    if not re.fullmatch(r'WGC_[A-F0-9]{12}', schema) or not re.fullmatch(r'[1-9][0-9]{0,18}', player):
        raise ValueError('Invalid fixture schema or character ID')
    # Trees without zone instances have no objects.zone_instance_id column.
    instance = 'to_char(zone_instance_id)' if zone_instances else "'" + server_profile.NO_INSTANCE + "'"
    return f"""select json_object('id' value to_char(object_id),
      'scene' value scene_id,'instance' value {instance},
      'x' value x,'y' value y,'z' value z,'container' value to_char(contained_by),
      'deleted' value deleted) from {schema}.objects where object_id={player};"""


def saved(project, schema, player):
    if not re.fullmatch(r'[1-9][0-9]{0,18}', player):
        raise ValueError('Invalid created character ID')
    rows = sql(project, schema, saved_query(schema, player, server_profile.active().zone_instances))
    if len(rows) != 1 or rows[0]['deleted'] != 0:
        raise RuntimeError('Created character has no unique live saved object')
    return rows[0]


def fixture_workers(log, zone_instances=True):
    """Game server ids Central registered; with zone instances only canonical definitions count."""
    found = re.findall(r'Adding server ([0-9]+) for scene (\w+)', log)
    if zone_instances:
        from instance_scope import load as family_scope
        definitions={row['definition'] for row in family_scope()['definitions']}
        found = [m for m in found if m[1] in definitions]
    return sorted({int(m[0]) for m in found})


def console_text(project, bot, command, worker, profile):
    """One typed fixture console request for this bot on one game server."""
    if profile.bot_console == 'binary':
        return run(['docker', 'exec', project + '-central-1', '/fixture/protocol-bot-console', '127.0.0.1',
                    command, str(worker), bot['player'], bot['station'], bot['character']], timeout=12)
    import restoration_console
    line = restoration_console.line(command, worker, bot)
    host = restoration_console.central_address(json.loads(run(['docker', 'inspect', project + '-central-1'])))
    try:
        return restoration_console.request(host, line, timeout=12)
    except OSError as exc:
        raise RuntimeError('Fixture console request failed') from exc


def bot_query(project, bot, command='botInspect', *, worker=None, _rescan=True):
    profile = server_profile.active()
    if worker is not None:
        if command!='botInspect' or type(worker) is not int or not 0<worker<=2147483647:
            raise ValueError('A worker hint is restricted to bounded read-only inspection')
        workers=[worker]
    else:
        log = run(['docker', 'exec', project + '-central-1', 'cat', profile.runtime_log])
        workers = fixture_workers(log, profile.zone_instances)
        if not workers or len(workers) > 64:
            raise RuntimeError('Cannot bound current fixture workers')
    if command != 'botInspect':
        current = bot_query(project, bot)
        if current is None:
            return None
        workers = [current['worker']]
    found = []
    inspected = 0
    for candidate_worker in workers:
        # Retry observations only. Replaying a timed-out setup could perform
        # the mutation twice; it must instead fail with its evidence intact.
        for attempt in range(3 if command == 'botInspect' else 1):
            try:
                text = console_text(project, bot, command, candidate_worker, profile)
                break
            except (RuntimeError, subprocess.TimeoutExpired):
                if command != 'botInspect' or attempt == 2:
                    raise
                print(json.dumps({'event': 'observation_retry', 'worker': candidate_worker, 'attempt': attempt+1}), flush=True)
                time.sleep(.25)
        if command == 'botInspect' and text in ('No game servers available to service request', 'game: Command not found.'):
            continue
        inspected += 1
        if not text and command in ('botRryattDeath','botRryattResurrect'):
            # Never replay a mutation after an uncertain console reply. Require
            # a fresh acceptance receipt on this same authoritative bot.
            # The scenario separately verifies the resulting player state.
            observed=bot_query(project,bot)
            if (observed and all(observed.get(k)==current.get(k) for k in ('worker','scene','instance')) and
                    observed.get('fixture_setup_action')==command and
                    int(observed.get('fixture_setup_serial','0'))==int(current.get('fixture_setup_serial','0'))+1 and
                    observed.get('fixture_setup_accepted')=='true'):
                text='protocol_bot=rryatt-setup accepted=true receipt=authoritative-observation serial='+observed['fixture_setup_serial']
        if text == 'protocol_bot=absent':
            continue
        if not text.startswith('protocol_bot=') or 'invalid-' in text:
            raise RuntimeError('Bot scope/identity inspection failed for ' + command + ': ' + repr(text))
        fields = dict(item.split('=', 1) for item in text.split())
        fields['worker'] = candidate_worker
        found.append(fields)
    if len(found) > 1:
        # Worker reads are sequential: a handoff can finish between source and
        # destination observations. Discard that census and read once afresh.
        # Persistent duplicates still fail; mutations are never replayed.
        if command == 'botInspect' and worker is None and _rescan:
            print(json.dumps({'event': 'handoff_census_retry',
                              'workers': [row['worker'] for row in found]}), flush=True)
            return bot_query(project, bot, _rescan=False)
        raise RuntimeError('Multiple authoritative bot actors')
    if not inspected:
        # A retired cached hint is not a global absence proof. Let its caller
        # discover the current authoritative worker; full census still refuses
        # to claim unload when no current worker could be inspected.
        if worker is not None:
            return None
        raise RuntimeError('No current fixture worker could be inspected')
    return found[0] if found else None


def unloaded(project, bot, timeout=240):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = bot_query(project, bot)
        if row is None:
            return
        if row.get('connected') == 'true':
            raise RuntimeError('Bot remains connected after accepted logout')
        time.sleep(3)
    raise TimeoutError('Bot full-unload deadline')


def settled(project, bot, family=None, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = bot_query(project, bot)
        if row and row.get('connected') == 'true' and row.get('pending') == 'false' and row.get('protected') == 'false' and row.get('outstanding') == 'false':
            if family is None or row.get('family') == family:
                return row
        time.sleep(1)
    raise TimeoutError('Bot arrival/settlement deadline')


class Session:
    def __init__(self, project, binary, config, evidence):
        self.events = []
        self.lines = queue.Queue(maxsize=4096)
        self.error = None
        self.log = evidence.open('x')
        self.process = subprocess.Popen(['docker', 'exec', '-i', '-e',
            'LD_LIBRARY_PATH=' + server_profile.active().library_path,
            project + '-game-1', binary, config], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        try:
            total = 0
            for line in self.process.stdout:
                total += len(line)
                if len(line) > 65536 or total > 8 * 1024 * 1024:
                    raise RuntimeError('Peer output bound exceeded')
                self.log.write(line)
                self.log.flush()
                if line.startswith('DRIVER '):
                    event = json.loads(line[7:])
                    if event.get('schema_version') != 1:
                        raise RuntimeError('Unknown peer event schema')
                    event['received_monotonic'] = time.monotonic()
                    self.lines.put(event, timeout=1)
        except Exception as exc:
            self.error = exc
        finally:
            self.lines.put(None, timeout=1)

    def wait(self, name, timeout=90, after=None):
        return self.wait_any((name,),timeout,after)

    def wait_any(self, names, timeout=90, after=None):
        if not isinstance(names,tuple) or not 1<=len(names)<=4 or any(not isinstance(n,str) or not n for n in names):
            raise ValueError("Bounded explicit milestones required")
        name=" or ".join(names)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                event = self.lines.get(timeout=min(1, max(.01, deadline-time.monotonic())))
            except queue.Empty:
                continue
            if event is None:
                raise RuntimeError('Peer exited before ' + name + ': ' + str(self.error))
            self.events.append(event)
            print(json.dumps(event), flush=True)
            if event['event'] == 'failure':
                raise RuntimeError(event['reason'])
            if event['event'] in names and (after is None or event['received_monotonic']>=after):
                return event
        raise TimeoutError('No peer milestone: ' + name)

    def send(self, command):
        self.process.stdin.write(command + '\n')
        self.process.stdin.flush()

    def close(self):
        if self.process.poll() is None:
            try:
                last_scene = next((e.get('scene', '') for e in reversed(self.events) if e['event'] == 'scene_ready'), '')
                if last_scene.startswith('terrain/space_'):
                    # Failure cleanup closes a piloted peer; sitting on the
                    # ground is not a valid logout precondition for this case.
                    self.send('quit')
                elif any(e['event'] == 'scene_ready' for e in self.events):
                    self.send('logout')
                    self.wait('logout_accepted', 40)
                else:
                    self.send('quit')
                self.process.wait(timeout=6)
            except (BrokenPipeError, subprocess.TimeoutExpired, RuntimeError, TimeoutError):
                try:
                    self.send('quit')
                    self.process.wait(timeout=6)
                except (BrokenPipeError, subprocess.TimeoutExpired):
                    self.process.terminate()
                    self.process.wait(timeout=5)
        self.thread.join(timeout=2)
        self.log.close()


def finish_peer(session, disconnect=False):
    """Keep deliberate client disconnect distinct from accepted game logout."""
    session.send('quit' if disconnect else 'logout')
    session.wait('disconnect_requested' if disconnect else 'logout_accepted', 10 if disconnect else 40)
    code = session.process.wait(timeout=10)
    if code != 0:
        raise RuntimeError('Peer exited with failure')
    return code


def complete_ground_arrival(session, query, expected, timeout=120, *, clock=time.monotonic, sleep=time.sleep):
    """Complete the original loading handshake after an observed destination.

    Same-world cell travel may send only a teleport. A new CmdStartScene is not
    required. Callers must still prove native settlement and protection expiry.
    """
    if (set(expected) != {'scene','family','room'} or expected['scene'] != 'dungeon1' or
            expected['family'] not in ('npe_space_station','npe_space_dungeon') or
            expected['room'] not in ('hangarbay1','cave_entrance')):
        raise ValueError('Authored public shuttle arrival required')
    deadline=clock()+timeout
    while clock()<deadline:
        row=query('botInspect')
        positioned=False
        if row:
            try:
                positioned=bool(re.fullmatch(r'-?[1-9][0-9]{0,18}',row.get('cell','')) and
                    re.fullmatch(r'[0-9]{1,20}',row.get('instance','')) and
                    all(math.isfinite(float(row.get(k,'nan'))) for k in ('x','y','z')))
            except (ValueError,TypeError):pass
        if (row and positioned and row.get('connected')=='true' and
                all(row.get(k)==v for k,v in expected.items())):
            requested=clock()
            session.send('awaitReady')
            ready=session.wait('action_ready',30,after=requested)
            if ready.get('scene')!='terrain/dungeon1.trn':
                raise RuntimeError('Client loading completion has an unexpected scene')
            return {'observed_destination':row,'readiness':ready}
        sleep(.25)
    raise TimeoutError('Authored shuttle destination was not observed before loading completion')


def station_setup_command(row):
    if row.get('dead')!='false' or row.get('instance')!='0':
        raise RuntimeError('Living original-world actor required for station fixture setup')
    if row.get('scene')=='kashyyyk_main':return 'botKashyyykHome'
    if row.get('scene')=='tutorial':return 'botStation'
    raise RuntimeError('Unreviewed station fixture setup origin')


def assert_saved_point(before, stored):
    cell=before.get('cell');expected='0' if cell in ('null','0') else cell
    if (expected is None or stored.get('scene')!=before.get('scene') or stored.get('instance')!=before.get('instance') or
            stored.get('container')!=expected or any(not math.isfinite(float(row[k])) for row in (before,stored) for k in ('x','y','z')) or
            any(abs(float(stored[k])-float(before[k]))>.01 for k in ('x','y','z'))):
        raise RuntimeError('Saved object does not match settled room and position')


def validate_binary(binary):
    """Reusable producer check for the CLI and typed Studio journeys."""
    binary = binary.resolve(strict=True)
    header = binary.read_bytes()[:20]
    if header[:6] != b'\x7fELF\x02\x01' or header[18:20] != b'\x3e\x00':
        raise ValueError('Requires an ELF64 little-endian x86-64 binary')
    build = json.loads(binary.with_suffix('.build.json').read_text())
    if (build.get('schema_version') != 1 or
            build.get('source_sha256') != hashlib.sha256(Path(__file__).with_name('protocol_driver64.cpp').read_bytes()).hexdigest() or
            build.get('companion_header_sha256') != hashlib.sha256(Path(__file__).with_name('ProtocolCompanionRoster.h').read_bytes()).hexdigest() or
            build.get('binary_sha256') != hashlib.sha256(binary.read_bytes()).hexdigest()):
        raise ValueError('Driver source/build provenance changed; build a fresh matching ELF64 artifact')
    return binary, build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--bot', required=True, help='retained identity key, lowercase letters, 3â€“16 characters')
    parser.add_argument('--create', action='store_true', help='create exactly one dedicated character if absent')
    parser.add_argument('--disconnect', action='store_true', help='close the protocol client explicitly instead of testing the sitting/logout action')
    parser.add_argument('--clone-scene', choices=('kashyyyk_main',), help='select the original clone menu for an already-dead public Kashyyyk actor')
    parser.add_argument('--terminal', help='positive or negative network ID; must be offered by the live server')
    parser.add_argument('--stage-station', action='store_true', help='explicit dedicated-bot setup at the retained fixture\'s authored Tansaari entrance')
    parser.add_argument('--prepare-terminal', action='store_true', help='position only this bot beside its own station shuttle, then test that real terminal')
    parser.add_argument('--position-terminal-only', action='store_true', help='save explicit dedicated-bot terminal-proximity setup in its own lifecycle')
    parser.add_argument('--menu-type', type=int, default=21, help='server-offered radial type (ITEM_USE=21)')
    parser.add_argument('--answer', choices=('ok', 'cancel'), default='ok')
    parser.add_argument('--prompt', help='exact expected message-box prompt for an explicit --terminal')
    parser.add_argument('--expect-scene', help='assert scene after the terminal confirmation')
    parser.add_argument('--expect-family', choices=('npe_space_station', 'npe_space_dungeon'), help='assert settled public-content destination (Gamma is npe_space_dungeon)')
    parser.add_argument('--require-hosted-public-instance', action='store_true', help='require explicit complete positive-host fixture and independently current native world evidence for this saved login')
    args = parser.parse_args()
    if args.clone_scene and (args.create or args.stage_station or args.prepare_terminal or args.position_terminal_only or args.terminal or args.disconnect):
        parser.error('Clone recovery is a separate original-menu and normal-logout lifecycle')
    if args.create and (args.stage_station or args.prepare_terminal or args.position_terminal_only or args.terminal):
        parser.error('Creation is a separate saved lifecycle; rerun the retained bot for fixture setup or terminal tests')
    if args.stage_station and (args.prepare_terminal or args.position_terminal_only or args.terminal):
        parser.error('Station setup is a separate saved lifecycle; relog the retained bot before terminal testing')
    if args.position_terminal_only and (args.prepare_terminal or args.terminal):
        parser.error('Terminal positioning is a separate setup lifecycle')
    if not re.fullmatch(r'[a-z]{3,16}', args.bot):
        parser.error('Invalid bot registry key')
    if args.terminal and not re.fullmatch(r'-?[1-9][0-9]{0,18}', args.terminal):
        parser.error('Invalid terminal ID')
    if args.terminal and not args.prompt:
        parser.error('Explicit terminal requests require an exact --prompt')
    if not 0 <= args.menu_type <= 65535:
        parser.error('Invalid menu type')
    profile = server_profile.active()
    if profile.session_options is not None:
        refused = sorted(key for key in ('clone_scene', 'terminal', 'stage_station', 'prepare_terminal',
                                         'position_terminal_only', 'prompt', 'expect_family',
                                         'require_hosted_public_instance') if getattr(args, key))
        if refused:
            parser.error('The ' + profile.name + ' server profile does not support: ' + ', '.join(refused))
    try:
        binary, build = validate_binary(args.binary)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    os.umask(0o077)
    with operation_lock(REPO / profile.deployment):
        project, schema, services = fixture(args.folder)
        hosted_worlds = None
        if args.require_hosted_public_instance:
            from hosted_public_login import precondition
            hosted_worlds = precondition(args.folder.resolve(),project,lambda command:run(['docker','exec',services['central']['Id'],
                '/fixture/client-console','127.0.0.1',command]))
        base = args.folder.resolve() / 'protocol-driver'
        base.mkdir(mode=0o700, exist_ok=True)
        registry = base / (args.bot + '.json')
        if registry.exists():
            bot = identity(json.loads(registry.read_text()))
        elif args.create:
            if len(list(base.glob('*.json'))) >= 8:
                parser.error('Dedicated bot budget is eight retained identities; reuse a bot')
            bot = identity({'schema_version': 1, 'account': 'capbot_' + secrets.token_hex(4)[:7],
                'character': 'Cap' + ''.join(secrets.choice('abcdefghijklmnopqrstuvwxyz') for _ in range(12))})
            registry.write_text(json.dumps(bot, indent=2) + '\n')
        else:
            parser.error('Unknown bot; first run requires --create')
        if bot.get('player') and bot.get('station'):
            unloaded(project, bot)
        operation = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + secrets.token_hex(3)
        folder = base / operation
        folder.mkdir(mode=0o700)
        config = folder / 'driver.cfg'
        config.write_text(f"[ProtocolDriver64]\nproject={project}\naccount={bot['account']}\ncharacter={bot['character']}\nship={bot.get('ship', '')}\ncreate={'true' if args.create else 'false'}\ntimeoutSeconds=300\n")
        destination = '/tmp/protocol-driver-' + operation
        container = project + '-game-1'
        run(['docker', 'exec', container, 'mkdir', '-m', '700', destination])
        run(['docker', 'cp', str(binary), container + ':' + destination + '/driver'])
        run(['docker', 'cp', str(config), container + ':' + destination + '/driver.cfg'])
        run(['docker', 'exec', container, 'chmod', '700', destination + '/driver'])
        report = {'schema_version': 1, 'operation': operation, 'project': project, 'schema': schema,
            'bot': bot, 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
            'source_sha256': hashlib.sha256(Path(__file__).with_name('protocol_driver64.cpp').read_bytes()).hexdigest(),
            'container_id': services['game']['Id'], 'image_id': services['game']['Image'],
            'created_images': 0, 'created_databases': 0, 'passed': False}
        session = None
        try:
            session = Session(project, destination + '/driver', destination + '/driver.cfg', folder / 'peer.log')
            scene = session.wait('scene_ready')
            player = scene['character']
            if bot.get('player') and bot['player'] != player:
                raise RuntimeError('Retained character identity changed')
            bot['player'] = player
            bot['station'] = next(e['station_id'] for e in session.events if e['event'] == 'authenticated')
            registry.write_text(json.dumps(bot, indent=2) + '\n')
            report['login'] = scene
            report['login_settled'] = settled(project, bot)
            if hosted_worlds is not None:
                from hosted_public_login import assert_login
                assert_login(report['login_settled'],hosted_worlds)
                report['hosted_public_world_proof'] = sorted([list(w) for w in hosted_worlds])
            # CmdStartScene precedes login scripts. Let their ordinary
            # initialization finish before deliberately staging a new bot.
            time.sleep(3)
            if args.clone_scene:
                from protocol_clone import execute
                report['clone_recovery'] = execute(project, bot, session, args.clone_scene)
            if args.stage_station:
                command = station_setup_command(report['login_settled'])
                report['station_setup_command'] = command
                report['station_setup'] = bot_query(project, bot, command)
                if not report['station_setup'] or report['station_setup'].get('accepted') != 'true':
                    raise RuntimeError('Dedicated station setup refused')
                report['station_settled'] = settled(project, bot, 'npe_space_station')
                session.send('awaitReady')
                session.wait('action_ready', 30)
            if args.prepare_terminal or args.position_terminal_only:
                preview = bot_query(project, bot, 'botTerminals')
                if not preview or preview.get('protocol_bot') != 'terminal':
                    raise RuntimeError('Unique terminal preview unavailable')
                report['terminal_setup_preview'] = preview
                setup = bot_query(project, bot, 'botPrepare')
                if not setup or setup.get('accepted') != 'true' or setup.get('target') != preview['target']:
                    raise RuntimeError('Terminal setup refused')
                report['terminal_setup'] = setup
                session.send('awaitReady')
                session.wait('action_ready', 30)
                report['terminal_source'] = settled(project, bot)
                if args.prepare_terminal and args.expect_family:
                    report['expected_terminal_room'] = authored_shuttle_room(
                        report['terminal_source']['family'], args.expect_family)
                if args.prepare_terminal:args.terminal = preview['target']
                else:report['position_terminal_only'] = True
            if args.terminal:
                session.send('menu ' + args.terminal)
                menu = session.wait('menu', 15)
                if menu['target'] != args.terminal or args.menu_type not in [r['type'] for r in menu['items']]:
                    raise RuntimeError('Required terminal action was not offered')
                session.send(f'select {args.terminal} {args.menu_type}')
                page = session.wait('sui', 15)
                prompt = '@npe:gamma_shuttle_prompt' if args.prepare_terminal else args.prompt
                deadline = time.monotonic() + 15
                while not expected_prompt(page, prompt):
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Expected terminal confirmation unavailable')
                    page = session.wait('sui', max(.1, deadline-time.monotonic()))
                report['terminal_page'] = page
                session.send(f"answer {page['page']} {args.answer}")
                session.wait('sui_answered', 10)
                ground_arrival=None
                if args.prepare_terminal and args.answer=='ok' and args.expect_family:
                    ground_arrival=complete_ground_arrival(session,lambda command:bot_query(project,bot,command),
                        dict(scene='dungeon1',family=args.expect_family,room=report['expected_terminal_room']))
                    report['terminal_loading_complete']=ground_arrival
                if args.expect_scene and ground_arrival:
                    arrival=ground_arrival['readiness']
                    if arrival.get('scene')!=args.expect_scene:raise RuntimeError('Unexpected terminal destination')
                    report['terminal_arrival']=arrival
                elif args.expect_scene:
                    arrival = session.wait('scene_ready', 60)
                    if arrival['scene'] != args.expect_scene:
                        raise RuntimeError('Unexpected terminal destination')
                    report['terminal_arrival'] = arrival
                if args.expect_family:
                    report['terminal_settled'] = settled(project, bot, args.expect_family)
                    if args.prepare_terminal:
                        expected_room = report['expected_terminal_room']
                        if report['terminal_settled'].get('room') != expected_room:
                            raise RuntimeError('Shuttle arrived in the wrong authored entrance room')
            before = settled(project, bot, args.expect_family)
            if hosted_worlds is not None:assert_login(before,hosted_worlds)
            report['before_disconnect' if args.disconnect else 'before_logout'] = before
            if args.expect_scene and 'terrain/'+before['scene']+'.trn' != args.expect_scene:
                raise RuntimeError('Settled scene differs from the requested assertion')
            report['exit_mode'] = 'client_disconnect' if args.disconnect else 'game_logout'
            report['peer_exit_code'] = finish_peer(session, args.disconnect)
            unloaded(project, bot)
            report['fully_unloaded'] = True
            report['saved'] = saved(project, schema, player)
            stored = report['saved']
            if args.clone_scene or before.get('family') in ('npe_space_station', 'npe_space_dungeon'):
                assert_saved_point(before, stored)
            report['passed'] = True
        except Exception as exc:
            report['error'] = str(exc)
            raise
        finally:
            if session:
                report['events'] = session.events
                session.close()
            (folder / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
            print('Evidence: ' + str(folder), flush=True)
            # Only this operation's temporary peer/config are removed. Evidence and bot persist.
            run(['docker', 'exec', container, 'rm', '-f', destination + '/driver', destination + '/driver.cfg'])
            run(['docker', 'exec', container, 'rmdir', destination])


if __name__ == '__main__':
    main()
