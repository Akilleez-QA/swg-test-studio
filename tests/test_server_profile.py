"""Server profiles: whitengold stays as it was; restoration is lean, tolerant and still isolated.

Each test also runs its check against a seeded fault, to show the check can fail.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from swg_test_studio import agent_fixture, docker_runtime
from swg_test_studio.backend import plan, require_profile_support, validate_environment
from swg_test_studio.cli import main as cli_main
from swg_test_studio.model import loads
from swg_test_studio.server_tools import TOOLS_ROOT
from swg_test_studio.setup import setups_folder
from swg_test_studio.store import EXAMPLES
from devtools.zones import restoration_console, server_profile
from devtools.zones.studio_tool_bundle import verify

ROOT = Path(__file__).resolve().parents[1]
RESTORATION_TREE = Path(os.environ.get("SWG_RESTORATION_TREE", "/home/akilleez/LOCAL LLM/swg-december-2011"))
HAVE_TREE = (RESTORATION_TREE / "src/engine/server/application/CentralServer/Makefile.am").is_file()
LEAN = TOOLS_ROOT / "zones/fixtures/restoration/protocol_bot.java"
ORIGINAL = TOOLS_ROOT / "zones/fixtures/protocol_bot.java"
INSTANCE_API = ("getZoneInstanceId", "getCurrentZoneInstanceId", "requestZoneInstance", "isSoloInstanceEligible",
                "getPrivateInstanceSession", "warpPlayerToInstance", "capacity_login", "capacity.")
# sha256 of the four plans below as the code before profiles produced them.
PLANS_BEFORE_PROFILES = "75968fe1520d0c834dc23eb78025b32ddeb08ccbd1274e9e8f010f54e0f01957"
# sha256 of the original WhiteNGold source list (the body of source_hashes) before profiles.
WHITENGOLD_LIST_BEFORE_PROFILES = "2489e9fd0ad177c282e1dfab5bc3afc11f5f2bdf1aa6f9c7ba2070a62a89e4d3"
ORIGINAL_SAVED_QUERY = """select json_object('id' value to_char(object_id),
      'scene' value scene_id,'instance' value to_char(zone_instance_id),
      'x' value x,'y' value y,'z' value z,'container' value to_char(contained_by),
      'deleted' value deleted) from WGC_012345ABCDEF.objects where object_id=42;"""


def env(**changes):
    data = {"schema_version": 1, "name": "Isolated SWG", "server_checkout": "/srv/swg",
            "folder": "/tmp/swg-cold-test-0123abcd/client-012345abcdef", "binary": "/tmp/swg-driver64/driver",
            "bindings": {"actor": "tester", "leader": "alpha", "member": "beta"}}
    data.update(changes)
    return data


def example(name):
    return loads((EXAMPLES / (name + ".json")).read_text(encoding="utf-8"))


def plans_digest(environment):
    plans = {name: plan(example(name), environment)
             for name in ("login_relogin", "create_character", "ship_and_group", "gamma_shuttle")}
    return hashlib.sha256(json.dumps(plans, sort_keys=True).encode()).hexdigest()


def whitengold_list_digest(text):
    body = text[text.index("    from protocol_native_gates import GATES\n"):text.index("def runtime_artifact")]
    return hashlib.sha256(body.encode()).hexdigest()


def instance_calls(text):
    return sorted(name for name in INSTANCE_API if name in text)


def tool(source, profile, program):
    """Run a snippet in a fresh process bound to one server source and profile; returns its JSON."""
    prelude = ("import json, sys\nfrom pathlib import Path\n"
               "from swg_test_studio.backend import driver_modules\n"
               "from swg_test_studio.server_tools import load_tool, tool_environment\n"
               "env = {'server_checkout': sys.argv[1]}\n"
               "if sys.argv[2] != '-': env['profile'] = sys.argv[2]\n"
               "driver, legacy = driver_modules(env)\n")
    result = subprocess.run([sys.executable, "-B", "-c", prelude + program, str(source), profile or "-"],
                            cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "tool failed")
    return json.loads(result.stdout)


def server_source(folder):
    source = Path(folder)
    for component in ("src/engine/server/application/CentralServer", "src/game/server/application/SwgGameServer"):
        (source / component).mkdir(parents=True)
        (source / component / "Makefile.am").touch()
    return source


class DefaultProfileTests(unittest.TestCase):
    def test_whitengold_plans_are_what_they_were_before_profiles(self):
        self.assertEqual(plans_digest(env()), PLANS_BEFORE_PROFILES)
        self.assertEqual(plans_digest(env(profile="whitengold")), PLANS_BEFORE_PROFILES)
        self.assertNotIn("profile", plan(example("login_relogin"), env()))
        # Seeded fault: any difference in a plan changes the digest.
        self.assertNotEqual(plans_digest(env(name="Another fixture")), PLANS_BEFORE_PROFILES)

    def test_whitengold_source_list_and_constants_are_unchanged(self):
        text = (TOOLS_ROOT / "zones/protocol_test_sets.py").read_text(encoding="utf-8")
        self.assertEqual(whitengold_list_digest(text), WHITENGOLD_LIST_BEFORE_PROFILES)
        # Seeded fault: dropping one pinned file from the list is detected.
        self.assertNotEqual(whitengold_list_digest(text.replace("'capacity_console.cpp', ", "", 1)),
                            WHITENGOLD_LIST_BEFORE_PROFILES)
        default = server_profile.get()
        self.assertEqual((default.name, default.server_root, default.deployment), ("whitengold", "/opt/whitengold", "StarWarsGalaxies"))
        self.assertEqual(default.runtime_log, "/opt/whitengold/exe/linux/runtime.log")
        self.assertEqual(default.runtime_scripts, agent_fixture.RUNTIME_SCRIPTS)
        self.assertEqual(default.library_path, "/opt/whitengold/lib:/opt/whitengold/jvm/lib/server:/opt/whitengold/jvm/lib")
        self.assertEqual(setups_folder(default), Path("StarWarsGalaxies/logs/studio-setups"))
        self.assertEqual(default.fixtures, ("fixtures/agent_fixture.java",))
        self.assertTrue(default.zone_instances and default.capacity_console and default.restart_journals)
        self.assertIsNone(default.source_inputs)
        self.assertEqual(server_profile.unsupported([{"id": "any", "kind": "ship_group", "options": {}}], default), [])

    @unittest.skipUnless(sys.platform == "linux", "Server tool imports require Linux")
    def test_whitengold_hashing_and_query_stay_strict_in_a_tool_process(self):
        with tempfile.TemporaryDirectory() as folder:
            source = server_source(folder)
            program = ("import os\nsaved = driver.saved_query('WGC_012345ABCDEF', '42', load_tool('zones/server_profile.py').active().zone_instances)\n"
                       "try:\n    legacy.source_hashes(); strict = False\nexcept OSError:\n    strict = True\n"
                       "print(json.dumps({'saved': saved, 'strict': strict, 'profile': load_tool('zones/server_profile.py').active().name,\n"
                       "    'child': tool_environment(driver.REPO).get('SWG_STUDIO_SERVER_PROFILE')}))\n")
            default = tool(source, None, program)
            self.assertEqual(default, {"saved": ORIGINAL_SAVED_QUERY, "strict": True, "profile": "whitengold", "child": None})
            # Seeded fault: the other profile gives a different query and does not raise.
            other = tool(source, "restoration", program)
            self.assertNotEqual(other["saved"], ORIGINAL_SAVED_QUERY)
            self.assertNotIn("zone_instance_id", other["saved"])
            self.assertIn("'instance' value 'none'", other["saved"])
            self.assertEqual((other["strict"], other["child"]), (False, "restoration"))


class RestorationPlanTests(unittest.TestCase):
    def test_environment_accepts_only_known_profiles_and_isolated_folders(self):
        self.assertEqual(validate_environment(env(profile="restoration"))["profile"], "restoration")
        self.assertNotIn("profile", validate_environment(env()))
        for bad in ("Restoration", "live", "", None, 3):
            with self.subTest(profile=bad), self.assertRaises(ValueError):
                validate_environment(env(profile=bad))
        # The profile never relaxes isolation: the same folder contract applies.
        for folder in ("/srv/swg/live", "/tmp/swg-cold-test-0123abcd", "/tmp/swg-cold-test-0123abcd/client-XYZ"):
            with self.subTest(folder=folder), self.assertRaises(ValueError):
                validate_environment(env(profile="restoration", folder=folder))

    def test_unsupported_suites_are_refused_before_any_run(self):
        restoration = env(profile="restoration")
        supported = set()
        for path in sorted(EXAMPLES.glob("*.json")):
            suite = loads(path.read_text(encoding="utf-8"))
            if "steps" not in suite:
                continue
            try:
                selected = plan(suite, dict(restoration, bindings={role: "bot" + "abcde"[i] for i, role in enumerate(suite["roles"])}))
            except ValueError as exc:
                self.assertIn("restoration server profile cannot run this test", str(exc), path.name)
            else:
                self.assertEqual(selected["profile"], "restoration")
                supported.add(suite["id"])
        self.assertEqual(supported, {"login_relogin", "create_character"})
        for name in ("gamma_shuttle", "ship_and_group", "terminal_journey", "driver_guards"):
            with self.subTest(suite=name):
                with self.assertRaisesRegex(ValueError, "restoration server profile cannot run"):
                    require_profile_support(example(name), "restoration")
                # Seeded fault: the same suite is accepted when the profile supports it.
                require_profile_support(example(name), "whitengold")
        with self.assertRaisesRegex(ValueError, "Unknown server profile"):
            require_profile_support(example("login_relogin"), "live")

    def test_session_options_and_agent_fixture_steps(self):
        restoration = server_profile.get("restoration")
        case = lambda **options: [{"id": "step", "kind": "protocol_session", "options": dict(role="actor", **options)}]
        for options in ({}, {"create": True}, {"disconnect": True}, {"expect_scene": "terrain/tatooine.trn"},
                        {"stage_station": False}):
            self.assertEqual(server_profile.unsupported(case(**options), restoration), [], options)
        for options in ({"stage_station": True}, {"prepare_terminal": True, "expect_family": "npe_space_dungeon"},
                        {"answer": "ok"}, {"require_hosted_public_instance": True}):
            self.assertTrue(server_profile.unsupported(case(**options), restoration), options)
        fixture = [{"id": "look", "kind": "agent_fixture", "options": {"role": "actor", "op": "inspect", "args": []}}]
        self.assertEqual(server_profile.unsupported(fixture, restoration), [])
        for kind in ("studio_journey", "studio_action_sequence", "ship_group", "driver_unit", "group_affinity_ord"):
            self.assertTrue(server_profile.unsupported([{"id": "x", "kind": kind, "options": {}}], restoration), kind)

    def test_validate_command_checks_a_named_profile(self):
        with tempfile.TemporaryDirectory() as workspace, patch("swg_test_studio.cli.emit") as emit:
            self.assertEqual(cli_main(["--workspace", workspace, "validate", "login_relogin", "--profile", "restoration"]), 0)
            self.assertEqual(emit.call_args.args[0], {"valid": True, "suite": "login_relogin", "profile": "restoration"})
            self.assertEqual(cli_main(["--workspace", workspace, "validate", "gamma_shuttle", "--profile", "restoration"]), 1)
            self.assertIn("restoration server profile cannot run", emit.call_args.args[0]["error"])
            self.assertEqual(cli_main(["--workspace", workspace, "validate", "gamma_shuttle"]), 0)
            self.assertEqual(emit.call_args.args[0], {"valid": True, "suite": "gamma_shuttle"})

    @unittest.skipUnless(HAVE_TREE and sys.platform == "linux", "The restoration server tree is not on this machine")
    def test_login_relogin_plans_and_hashes_against_the_restoration_tree(self):
        selected = plan(example("login_relogin"), env(profile="restoration", server_checkout=str(RESTORATION_TREE)))
        self.assertEqual(selected["profile"], "restoration")
        self.assertEqual([case["kind"] for case in selected["manifest"]["tests"]], ["protocol_session"] * 2)
        program = "print(json.dumps({'repo': str(driver.REPO), 'hashes': legacy.source_hashes()}))\n"
        report = tool(RESTORATION_TREE, "restoration", program)
        self.assertEqual(report["repo"], str(RESTORATION_TREE))
        hashes = report["hashes"]
        restoration = server_profile.get("restoration")
        for name in restoration.source_inputs:
            self.assertRegex(hashes["../../" + name], r"\A[a-f0-9]{64}\Z", name)
        for name in restoration.absent_inputs:
            self.assertEqual(hashes["../../" + name], "absent", name)
        for name in ("server_profile.py", "protocol_driver64.cpp", "fixtures/restoration/protocol_bot.java",
                     "fixtures/agent_fixture.java", "restoration_console.py"):
            self.assertRegex(hashes[name], r"\A[a-f0-9]{64}\Z", name)
        # Seeded fault: without the profile the same tree aborts every run on a missing WhiteNGold file.
        with self.assertRaises(RuntimeError) as failure:
            tool(RESTORATION_TREE, None, program)
        self.assertRegex(str(failure.exception), "FileNotFoundError|No such file")


class TolerantHashingTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "linux", "Server tool imports require Linux")
    def test_missing_inputs_are_recorded_as_absent_and_present_ones_hashed(self):
        restoration = server_profile.get("restoration")
        present, wng_only = restoration.source_inputs[0], restoration.absent_inputs[0]
        program = "print(json.dumps(legacy.source_hashes()))\n"
        with tempfile.TemporaryDirectory() as folder:
            source = server_source(folder)
            empty = tool(source, "restoration", program)
            listed = {"../../" + name for name in restoration.source_inputs + restoration.absent_inputs}
            self.assertEqual({name for name in empty if name.startswith("../../")}, listed)
            self.assertEqual({empty[name] for name in listed}, {"absent"})
            for name, content in ((present, b"first"), (wng_only, b"unexpected")):
                (source / name).parent.mkdir(parents=True, exist_ok=True)
                (source / name).write_bytes(content)
            filled = tool(source, "restoration", program)
            self.assertEqual(filled["../../" + present], hashlib.sha256(b"first").hexdigest())
            # A WhiteNGold-only file that does exist is hashed, not silently called absent.
            self.assertEqual(filled["../../" + wng_only], hashlib.sha256(b"unexpected").hexdigest())
            # Seeded fault: changed bytes change the record.
            (source / present).write_bytes(b"second")
            self.assertNotEqual(tool(source, "restoration", program)["../../" + present], filled["../../" + present])
            self.assertEqual({name: digest for name, digest in filled.items() if not name.startswith("../../")},
                             {name: digest for name, digest in empty.items() if not name.startswith("../../")})

    def test_every_restoration_input_names_a_server_file(self):
        restoration = server_profile.get("restoration")
        names = restoration.source_inputs + restoration.absent_inputs
        self.assertEqual(len(set(names)), len(names))
        for name in names:
            self.assertRegex(name, r"\A(src|dsrc)/[A-Za-z0-9_./]+\Z")
            self.assertNotIn("..", Path(name).parts)

    @unittest.skipUnless(HAVE_TREE, "The restoration server tree is not on this machine")
    def test_inputs_exist_in_the_restoration_tree_and_whitengold_only_files_do_not(self):
        restoration = server_profile.get("restoration")
        self.assertEqual([n for n in restoration.source_inputs if not (RESTORATION_TREE / n).is_file()], [])
        self.assertEqual([n for n in restoration.absent_inputs if (RESTORATION_TREE / n).exists()], [])
        # Seeded fault: the same check reports a name that is not in the tree.
        self.assertFalse((RESTORATION_TREE / "src/engine/server/library/serverUtility/src/shared/NoSuchFile.h").is_file())


class LeanFixtureTests(unittest.TestCase):
    def test_lean_fixture_has_no_zone_instance_calls(self):
        lean = LEAN.read_text(encoding="utf-8")
        self.assertEqual(instance_calls(lean), [])
        # Seeded fault: the same scan finds them in the original fixture.
        self.assertGreaterEqual(len(instance_calls(ORIGINAL.read_text(encoding="utf-8"))), 5)
        self.assertEqual(instance_calls(lean.replace('"+NONE+" cell=', '"+getZoneInstanceId(p)+" cell=')), ["getZoneInstanceId"])

    def test_lean_fixture_keeps_the_original_guards_and_reports_what_the_driver_reads(self):
        lean, original = LEAN.read_text(encoding="utf-8"), ORIGINAL.read_text(encoding="utf-8")
        guards = ('"1".equals(getConfigSetting("GameServer","clientIsolationFixture"))',
                  'schema.matches("WGC_[A-F0-9]{12}")', 'getConfigSetting("dbProcess","schemaOwner")',
                  '!fields[2].matches("Cap[a-z]{12}")', "!p.isAuthoritative() || !isPlayer(p)",
                  "!fields[2].equals(getPlayerFullName(p))",
                  "Integer.toUnsignedLong(getPlayerStationId(p))!=Long.parseLong(fields[1]) || isGod(p)")
        for guard in guards:
            self.assertIn(guard, original, guard)
            self.assertIn(guard, lean, guard)
        self.assertIn("package script.fixture;", lean)
        self.assertEqual(re.findall(r"public String (\w+)\(String value\)", lean), ["inspect"])
        report = lean[lean.index('return "protocol_bot=present'):]
        for field in ("player", "connected", "scene", "instance", "cell", "room", "x", "y", "z", "dead",
                      "family", "pending", "protected", "outstanding", "group"):
            self.assertRegex(report, r'[" ]' + field + "=", field)
        self.assertIn('" scene="+l.area+" instance="+NONE+', report)
        self.assertIn('private static final String NONE="none";', lean)
        self.assertEqual(server_profile.NO_INSTANCE, "none")
        for mutating in ("setLocation", "warpPlayer", "setObjVar", "attachScript", "createObject", "destroyObject",
                         "sendConsoleCommand", "messageTo"):
            self.assertNotIn(mutating, lean)

    @unittest.skipUnless(HAVE_TREE, "The restoration server tree is not on this machine")
    def test_lean_fixture_calls_exist_in_the_restoration_script_api(self):
        scripts = RESTORATION_TREE / "dsrc/sku.0/sys.server/compiled/game/script"
        api = (scripts / "base_class.java").read_text(encoding="latin-1")

        def missing(source):
            own = set(re.findall(r"(?:public|protected|private) [\w\[\].]+ (\w+)\(", source))
            calls = set(re.findall(r"(?<![.\w])([a-z][A-Za-z]+)\(", source)) - own - {"if", "for", "while", "return"}
            return sorted(name for name in calls if not re.search(r"\b" + name + r"\s*\(", api))

        self.assertEqual(missing(LEAN.read_text(encoding="utf-8")), [])
        # Seeded fault: the original fixture's instance calls are not in this API.
        self.assertIn("getZoneInstanceId", missing(ORIGINAL.read_text(encoding="utf-8")))


class RestorationRuntimeTests(unittest.TestCase):
    BOT = {"player": "2562923411", "station": "903905304", "character": "Capabcdefghijkl"}

    def test_typed_console_line_and_frame_match_the_agent_fixture_framing(self):
        line = restoration_console.line("botInspect", 12, self.BOT)
        self.assertEqual(line, "game 12 runScript fixture.protocol_bot inspect 2562923411:903905304:Capabcdefghijkl")
        self.assertEqual(restoration_console.frame(line), agent_fixture.pack(line))
        self.assertEqual(restoration_console.crc("ConGenericMessage"), agent_fixture.crc("ConGenericMessage"))
        self.assertNotEqual(restoration_console.frame(line), agent_fixture.pack(line + " extra"))
        for command, worker, bot in (("botStation", 12, self.BOT), ("botInspect", 0, self.BOT), ("botInspect", "12", self.BOT),
                                     ("botInspect", 12, dict(self.BOT, character="Admin")),
                                     ("botInspect", 12, dict(self.BOT, player="1 reloadScript x"))):
            with self.subTest(command=command, worker=worker), self.assertRaises(ValueError):
                restoration_console.line(command, worker, bot)
        for host in ("8.8.8.8", "::1", "example.org"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                restoration_console.private_address(host)

    def test_console_request_reads_one_reply_after_a_keepalive(self):
        reply = agent_fixture.pack("protocol_bot=absent\n")

        class Conn:
            def __init__(self):
                self.sent, self.data = b"", b"\x00\x00\x00\x00" + reply
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def sendall(self, data): self.sent += data
            def recv(self, size):
                chunk, self.data = self.data[:size], self.data[size:]
                return chunk

        conn = Conn()
        text = restoration_console.request("172.18.0.5", "game 1 runScript fixture.protocol_bot inspect x",
                                           connect=lambda address, timeout: conn)
        self.assertEqual(text, "protocol_bot=absent")
        self.assertEqual(conn.sent, restoration_console.frame("game 1 runScript fixture.protocol_bot inspect x"))
        closed = Conn()
        closed.data = b""
        with self.assertRaisesRegex(RuntimeError, "closed"):
            restoration_console.request("172.18.0.5", "x", connect=lambda address, timeout: closed)

    @unittest.skipUnless(sys.platform == "linux", "Server tool imports require Linux")
    def test_worker_discovery_does_not_need_instance_definitions(self):
        log = "Adding server 7 for scene tatooine\nAdding server 9 for scene not_a_wng_definition\nAdding server 7 for scene naboo\n"
        program = ("log = sys.stdin.read()\n"
                   "print(json.dumps([driver.fixture_workers(log, False), driver.fixture_workers('none', False)]))\n")
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, "-B", "-c",
                                     "import json, sys\nfrom swg_test_studio.backend import driver_modules\n"
                                     "driver, _ = driver_modules({'server_checkout': sys.argv[1], 'profile': 'restoration'})\n" + program,
                                     str(server_source(folder))], cwd=ROOT, input=log, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), [[7, 9], []])

    def test_readiness_needs_registered_scenes_and_no_capacity_console(self):
        restoration = server_profile.get("restoration")
        self.assertFalse(restoration.capacity_console or restoration.zone_instances or restoration.restart_journals)
        self.assertEqual(restoration.bot_console, "tcp")
        self.assertEqual(docker_runtime.registered_scenes("Adding server 3 for scene tatooine\nnoise\n"), {"tatooine"})
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "protocol-driver").mkdir()
            (folder / "protocol-driver/tester.json").write_text(json.dumps(self.BOT), encoding="utf-8")
            driver = SimpleNamespace(fixture=lambda path: ("swg-cold-test-0123abcd", "WGC_012345ABCDEF", {}),
                                     identity=lambda value: value,
                                     saved=lambda project, schema, player: {"scene": "tatooine", "instance": "none"})
            calls = []

            def fake_docker(*args, **kwargs):
                calls.append(args)
                return "Adding server 3 for scene tatooine\n" if len(calls) > 1 else "Adding server 3 for scene naboo\n"

            with patch.object(docker_runtime, "docker", side_effect=fake_docker):
                docker_runtime.wait_for_scene_workers(driver, folder, "central-id", {"actor": "tester", "new": "unmade"},
                                                      restoration, sleep=lambda _: None)
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0], ("exec", "central-id", "cat", "/opt/restoration/exe/linux/runtime.log"))
            self.assertFalse(any("client-console" in part or "capacity" in part for call in calls for part in call))
            # Seeded fault: a saved scene no game server registered is not ready.
            with patch.object(docker_runtime, "docker", return_value="Adding server 3 for scene naboo\n"), \
                    self.assertRaisesRegex(ValueError, "saved scenes"):
                docker_runtime.wait_for_scene_workers(driver, folder, "central-id", {"actor": "tester"}, restoration,
                                                      timeout=0, sleep=lambda _: None)

    def test_restoration_paths_are_profile_constants(self):
        restoration = server_profile.get("restoration")
        self.assertEqual(restoration.runtime_scripts, restoration.server_root + "/data/sku.0/sys.server/compiled/game/script")
        self.assertEqual(setups_folder(restoration), Path(restoration.deployment) / "logs/studio-setups")
        self.assertNotEqual(restoration.server_root, server_profile.get().server_root)
        self.assertNotIn("whitengold", restoration.library_path + restoration.runtime_log)
        self.assertEqual(agent_fixture.reload_command(4, "fixture.protocol_bot"), "game 4 reloadScript fixture.protocol_bot")
        with self.assertRaises(ValueError):
            agent_fixture.reload_command(4, "player.base.base_player")

    def test_bundle_manifest_covers_the_profile_files(self):
        files = verify(TOOLS_ROOT)
        for name in ("zones/server_profile.py", "zones/restoration_console.py", "zones/fixtures/restoration/protocol_bot.java"):
            self.assertEqual(files[name], hashlib.sha256((TOOLS_ROOT / name).read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
