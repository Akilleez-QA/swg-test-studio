"""Reusable guarded lifecycle around the existing ELF64 protocol peer.

No wire implementation, terminal setup or game commands are defined here.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets

PROTOCOL_PEER_VERSION = 1


@contextmanager
def open_peer(folder, binary, registry):
    from protocol_driver import (REPO, Session, fixture, identity, operation_lock, run,
                                 settled, unloaded, saved, assert_saved_point, finish_peer, validate_binary)
    if not isinstance(registry, str) or not re.fullmatch('[a-z]{3,16}', registry):
        raise ValueError('A dedicated retained registry key is required')
    binary, proof = validate_binary(Path(binary))
    folder = Path(folder).resolve(strict=True)
    os.umask(0o077)
    with operation_lock(REPO/'StarWarsGalaxies'):
        project, schema, services = fixture(folder)
        if any((folder/'fixture/teststudio').glob('*.control')):
            raise ValueError('Stop recording before automated replay')
        base = folder/'protocol-driver'
        bot = identity(json.loads((base/(registry+'.json')).read_text()))
        if not bot.get('player') or not bot.get('station'):
            raise ValueError('Studio journeys require an existing registered character')
        unloaded(project, bot)
        operation = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-studio-'+secrets.token_hex(4)
        evidence = base/operation
        evidence.mkdir(mode=0o700)
        destination = '/tmp/protocol-driver-'+operation
        container = services['game']['Id']
        report = dict(schema_version=1,operation=operation,project=project,schema=schema,passed=False,
                      fully_unloaded=False,client_source_changed=False,bot=bot,
                      binary_sha256=proof['binary_sha256'],setup=[],checks=[],cleanup_errors=[])
        from studio_tool_bundle import TOOLS_ROOT
        sources=[Path(__file__),TOOLS_ROOT.parent/'devtools/zones/protocol_driver.py',TOOLS_ROOT/'zones/fixtures/protocol_bot.java']
        report['adapter_version']=PROTOCOL_PEER_VERSION
        report['backend_sha256']={str(p.relative_to(TOOLS_ROOT.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        session = None
        original = None
        class Peer:
            def row(self):
                return settled(project,bot)
        peer=Peer()
        peer.report,peer.project,peer.bot,peer.evidence=report,project,bot,evidence
        try:
            if project=='swg-cold-test-d9d6e6af' and schema=='WGC_AE80ACB41011':
                from protocol_preservation import snapshot
                original=snapshot(project,schema)
                report['originals_before']={k:original[k] for k in ('objects','sha256')}
            config=evidence/'driver.cfg'
            config.write_text('[ProtocolDriver64]\nproject='+project+'\naccount='+bot['account']+
                              '\ncharacter='+bot['character']+'\nship='+bot.get('ship','')+'\ntimeoutSeconds=900\n')
            run(['docker','exec',container,'mkdir','-m','700',destination])
            run(['docker','cp',str(binary),container+':'+destination+'/driver'])
            run(['docker','cp',str(config),container+':'+destination+'/driver.cfg'])
            run(['docker','exec',container,'chmod','700',destination+'/driver'])
            session=Session(project,destination+'/driver',destination+'/driver.cfg',evidence/'peer.log')
            peer.session=session
            scene=session.wait('scene_ready',120)
            authenticated=next(e for e in session.events if e['event']=='authenticated')
            if scene['character']!=bot['player'] or str(authenticated['station_id'])!=bot['station']:
                raise RuntimeError('Retained login identity changed')
            peer.initial=settled(project,bot)
            report['login']=peer.initial
            yield peer
            before=settled(project,bot)
            if before.get('scene')!='dungeon1' or before.get('family') not in ('npe_space_station','npe_space_dungeon'):
                raise RuntimeError('Ground shuttle journey ended outside its supported public families')
            finish_peer(session)
            unloaded(project,bot)
            report['fully_unloaded']=True
            report['saved']=saved(project,schema,bot['player'])
            assert_saved_point(before,report['saved'])
            report['before_logout']=before
            report['passed']=True
        except BaseException as exc:
            report['error']=type(exc).__name__+': '+str(exc)
            raise
        finally:
            if session:
                try:
                    session.close()
                    unloaded(project,bot)
                    report['fully_unloaded']=True
                except Exception as exc:
                    report['cleanup_errors'].append(str(exc));report['passed']=False
            if original is not None:
                try:
                    from protocol_preservation import snapshot
                    after=snapshot(project,schema)
                    report['originals_after']={k:after[k] for k in ('objects','sha256')}
                    if original!=after:raise RuntimeError('Original character records changed')
                except Exception as exc:
                    report['cleanup_errors'].append(str(exc));report['passed']=False
            for name in ('driver','driver.cfg'):
                try:run(['docker','exec',container,'rm','-f',destination+'/'+name])
                except Exception as exc:report['cleanup_errors'].append(str(exc));report['passed']=False
            try:run(['docker','exec',container,'rmdir',destination])
            except Exception as exc:report['cleanup_errors'].append(str(exc));report['passed']=False
            for path in sources:
                try:
                    if hashlib.sha256(path.read_bytes()).hexdigest()!=report['backend_sha256'][str(path.relative_to(TOOLS_ROOT.parent))]:
                        raise RuntimeError('Adapter source changed during replay')
                except (OSError,RuntimeError) as exc:
                    report['cleanup_errors'].append(str(exc));report['passed']=False
            (evidence/'result.json').write_text(json.dumps(report,indent=2)+'\n')
        if not report['passed'] or not report['fully_unloaded']:
            raise RuntimeError('Replay cleanup or preservation failed; see '+str(evidence))
