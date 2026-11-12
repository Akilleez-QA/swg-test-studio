"""Server profiles: which server tree and prepared fixture Studio is driving.

`whitengold` is the original behaviour and the default. `restoration` drives a
server built from a tree without zone instances, capacity consoles or the
Test Studio recorder. A profile never relaxes fixture isolation: schema prefix,
container labels, image pins and the dedicated-bot guards are shared.

Selection: the environment file's optional "profile" key, bound once per
process by Studio and passed to tool subprocesses in SWG_STUDIO_SERVER_PROFILE.
"""
from dataclasses import dataclass
import os

ENV = 'SWG_STUDIO_SERVER_PROFILE'
DEFAULT = 'whitengold'
NO_INSTANCE = 'none'
SCRIPTS = '/data/sku.0/sys.server/compiled/game/script'


@dataclass(frozen=True)
class Profile:
    name: str
    server_root: str        # server install root inside the fixture containers
    deployment: str         # checkout sub-folder: management lock, image pins, registered setups
    zone_instances: bool    # objects.zone_instance_id and the zone-instance script API exist
    capacity_console: bool  # /fixture/client-console capacityScenes/capacityInstances readiness
    bot_console: str        # 'binary': /fixture/protocol-bot-console; 'tcp': typed ConGenericMessage
    restart_journals: bool  # stopped servers need the existing-journal maintenance before a start
    recording: bool         # TestStudioRecorder/TestStudioCapture are compiled into the server
    fixtures: tuple         # fixture sources (under devtools/zones) installed by install-agent-fixture
    case_kinds: frozenset   # supported compiled case kinds; None: every kind Studio compiles
    session_options: frozenset  # supported session options; None: all
    source_inputs: tuple    # server files hashed per run (None: the original WhiteNGold list)
    absent_inputs: tuple    # files of the other tree; recorded, expected to be absent
    client_kinds: frozenset = None  # supported client_action kinds (docs/fixture-client-actions.md); None: all

    @property
    def runtime_log(self):
        return self.server_root + '/exe/linux/runtime.log'

    @property
    def runtime_scripts(self):
        return self.server_root + SCRIPTS

    @property
    def library_path(self):
        root = self.server_root
        return f'{root}/lib:{root}/jvm/lib/server:{root}/jvm/lib'


_ENGINE = 'src/engine/'
_SCRIPT = 'dsrc/sku.0/sys.server/compiled/game/script/'
_MESSAGES = _ENGINE + 'shared/library/sharedNetworkMessages/src/shared/'
# What the driver peer, the typed console and the two restoration fixtures rely on.
RESTORATION_INPUTS = (
    # Console transport and command routing (game <id> runScript/reloadScript).
    _ENGINE + 'shared/library/sharedNetwork/src/linux/TcpClient.cpp',
    _ENGINE + 'shared/library/sharedNetwork/src/linux/TcpClient.h',
    _MESSAGES + 'clientGameServer/ConsoleChannelMessages.h',
    _ENGINE + 'server/application/CentralServer/src/shared/ConfigCentralServer.cpp',
    _ENGINE + 'server/application/CentralServer/src/shared/ConsoleConnection.cpp',
    _ENGINE + 'server/application/CentralServer/src/shared/ConsoleManager.cpp',
    _ENGINE + 'server/application/CentralServer/src/shared/ConsoleCommandParser.cpp',
    _ENGINE + 'server/library/serverGame/src/shared/console/CentralCommandParserGame.cpp',
    _ENGINE + 'server/library/serverGame/src/shared/console/ConsoleCommandParserScript.cpp',
    # Readiness lines Studio reads.
    _ENGINE + 'server/application/CentralServer/src/shared/CentralServer.cpp',
    _ENGINE + 'server/application/LoginServer/src/shared/LoginServer.cpp',
    # Login, scene start and logout as the peer drives them.
    _MESSAGES + 'clientLoginServer/ClientLoginMessages.h',
    _MESSAGES + 'clientGameServer/ClientCentralMessages.h',
    _MESSAGES + 'clientGameServer/SceneChannelMessages.h',
    _MESSAGES + 'clientGameServer/LogoutMessage.h',
    _ENGINE + 'server/library/serverGame/src/shared/core/Client.cpp',
    _ENGINE + 'server/library/serverGame/src/shared/core/Client.h',
    _ENGINE + 'server/library/serverGame/src/shared/core/GameServer.cpp',
    _ENGINE + 'server/library/serverGame/src/shared/object/CreatureObject.cpp',
    _ENGINE + 'server/library/serverGame/src/shared/object/ServerObject.cpp',
    # Script host and the API the fixtures compile against.
    _ENGINE + 'server/library/serverScript/src/shared/JavaLibrary.cpp',
    _ENGINE + 'server/library/serverScript/src/shared/ScriptMethodsScript.cpp',
    _ENGINE + 'server/library/serverScript/src/shared/ScriptMethodsWorldInfo.cpp',
    _ENGINE + 'server/library/serverScript/src/shared/ScriptMethodsObjectInfo.cpp',
    _SCRIPT + 'base_class.java',
    _SCRIPT + 'base_script.java',
    _SCRIPT + 'obj_id.java',
    _SCRIPT + 'location.java',
    _SCRIPT + 'library/utils.scriptlib',
    _SCRIPT + 'library/player_structure.scriptlib',
    _SCRIPT + 'library/static_item.scriptlib',
    # Saved-state query.
    'src/game/server/database/schema/objects.tab',
    # Client actions of held sessions (docs/fixture-client-actions.md): what the peer builds and what answers it.
    _MESSAGES + 'clientGameServer/SecureTradeMessages.h',
    _MESSAGES + 'clientGameServer/SecureTradeMessages.cpp',
    _MESSAGES + 'clientGameServer/MessageQueueSecureTrade.h',
    _MESSAGES + 'clientGameServer/MessageQueueSecureTrade.cpp',
    _MESSAGES + 'clientGameServer/MessageQueueCommandQueueEnqueue.cpp',
    _MESSAGES + 'chat/ChatInstantMessageToCharacter.cpp',
    _MESSAGES + 'chat/ChatOnSendInstantMessage.cpp',
    _MESSAGES + 'chat/ChatInstantMessageToClient.cpp',
    _ENGINE + 'server/library/serverGame/src/shared/controller/CreatureController.cpp',
    _ENGINE + 'server/library/serverGame/src/shared/trading/ServerSecureTrade.cpp',
    _ENGINE + 'server/library/serverGame/src/shared/trading/ServerSecureTradeManager.cpp',
    _ENGINE + 'server/library/serverGame/src/shared/command/CommandCppFuncs.cpp',
    _ENGINE + 'server/application/ConnectionServer/src/shared/ClientConnection.cpp',
    _ENGINE + 'server/application/ChatServer/src/shared/ConnectionServerConnection.cpp',
    'dsrc/sku.0/sys.shared/compiled/game/datatables/command/command_table.tab',
)
# Client actions a held session sends under restoration: all of them. None needs a zone instance,
# a station, a ship or the recorder; a group, a trade and a tell are ordinary player-to-player actions.
RESTORATION_CLIENT_KINDS = frozenset((
    'session_hold', 'session_release',
    'group_invite', 'group_join', 'group_decline', 'group_uninvite', 'group_leave', 'group_disband',
    'group_make_leader', 'group_dismiss',
    'trade_request', 'trade_accept', 'trade_deny', 'trade_add_item', 'trade_credits', 'trade_offer',
    'trade_unoffer', 'trade_verify', 'trade_reject', 'trade_cancel', 'tell'))
WHITENGOLD_ONLY = (
    _ENGINE + 'server/library/serverUtility/src/shared/ZoneInstanceScope.h',
    _ENGINE + 'server/library/serverGame/src/shared/core/TestStudioRecorder.h',
    _ENGINE + 'server/library/serverGame/src/shared/core/TestStudioCapture.h',
    _ENGINE + 'server/application/CentralServer/src/shared/PrivateDepartureJournal.h',
    _ENGINE + 'server/library/serverGame/src/shared/network/CapacityPlayerWorld.h',
    _SCRIPT + 'library/capacity_login.scriptlib',
)

PROFILES = {
    'whitengold': Profile(
        name='whitengold', server_root='/opt/whitengold', deployment='StarWarsGalaxies',
        zone_instances=True, capacity_console=True, bot_console='binary', restart_journals=True,
        recording=True, fixtures=('fixtures/agent_fixture.java',), case_kinds=None,
        session_options=None, source_inputs=None, absent_inputs=()),
    'restoration': Profile(
        name='restoration', server_root='/opt/restoration', deployment='StudioTestServer',
        zone_instances=False, capacity_console=False, bot_console='tcp', restart_journals=False,
        recording=False, fixtures=('fixtures/restoration/protocol_bot.java', 'fixtures/agent_fixture.java'),
        case_kinds=frozenset(('protocol_session', 'agent_fixture', 'client_action')),
        session_options=frozenset(('role', 'create', 'disconnect', 'expect_scene')),
        source_inputs=RESTORATION_INPUTS, absent_inputs=WHITENGOLD_ONLY,
        client_kinds=RESTORATION_CLIENT_KINDS),
}

_bound = None


def get(name=None):
    name = DEFAULT if name is None else name
    if not isinstance(name, str) or name not in PROFILES:
        raise ValueError('Unknown server profile; use one of: ' + ', '.join(sorted(PROFILES)))
    return PROFILES[name]


def bind(name=None):
    """One profile per process, like the selected server source."""
    global _bound
    profile = get(name)
    if _bound is not None and _bound is not profile:
        raise ValueError('Use a separate Studio process for a different server profile.')
    _bound = profile
    return profile


def active():
    if _bound is not None:
        return _bound
    return bind(os.environ.get(ENV) or DEFAULT)


def child_environment(env):
    """Give tool subprocesses the bound profile; the default leaves the environment as it was."""
    profile = active()
    env = dict(env)
    if profile.name == DEFAULT:
        env.pop(ENV, None)
    else:
        env[ENV] = profile.name
    return env


def unsupported(cases, profile):
    """Reasons this profile cannot run these compiled cases; empty when it can."""
    reasons = []
    if profile.case_kinds is None:
        return reasons
    for case in cases:
        if case['kind'] not in profile.case_kinds:
            reasons.append(f"{case['id']}: {case['kind']} steps")
        elif case['kind'] == 'protocol_session':
            extra = sorted(key for key, value in case['options'].items()
                           if key not in profile.session_options and value is not False)
            if extra:
                reasons.append(f"{case['id']}: session option " + ', '.join(extra))
        elif case['kind'] == 'client_action' and profile.client_kinds is not None:
            if case['options'].get('kind') not in profile.client_kinds:
                reasons.append(f"{case['id']}: client action {case['options'].get('kind')}")
    return reasons


def require_supported(cases, profile):
    reasons = unsupported(cases, profile)
    if reasons:
        raise ValueError(
            f'The {profile.name} server profile cannot run this test ({"; ".join(reasons)}). '
            'It supports plain login, character creation, disconnect and expected-scene sessions, '
            'agent_fixture steps and held-session client steps (group, trade, tell); zone instances, '
            'shuttles, ships, station-staged group sequences, journeys and recordings need the whitengold profile.')
