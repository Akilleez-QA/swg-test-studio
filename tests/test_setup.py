import contextlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from swg_test_studio import docker_runtime
from swg_test_studio.server_tools import SOURCE_ROOT_ENV, TOOLS_ROOT
from swg_test_studio.setup import assign_roles, saved_source, select_source


class SetupTests(unittest.TestCase):
    def test_readiness_allows_slow_source_validation_within_a_bounded_budget(self):
        def verify(argv, **kwargs):
            output = Path(argv[argv.index("--output") + 1])
            output.write_text('{"ready": true}', encoding="utf-8")
            self.assertEqual(Path(argv[1]), TOOLS_ROOT / "zones/inspect_client_fixture.py")
            self.assertEqual(kwargs["env"][SOURCE_ROOT_ENV], str(Path("/source")))
            self.assertGreater(kwargs["timeout"], 30)
            self.assertLessEqual(kwargs["timeout"], 300)
            return SimpleNamespace(returncode=0)

        with patch.object(docker_runtime.subprocess, "run", side_effect=verify) as run:
            docker_runtime.wait_for_preload(SimpleNamespace(REPO=Path("/source")), Path("/tmp/test/client"))
        run.assert_called_once()

    def test_find_starts_one_verified_server_if_none_are_running(self):
        setups = {"fixture-a": {"name": "First"}, "fixture-b": {"name": "Second"}}
        for second_state in ("Stopped", "Running"):
            with self.subTest(second_state=second_state), patch.object(docker_runtime, "require_docker"), \
                    patch.object(docker_runtime, "available_setups", return_value=setups), \
                    patch.object(docker_runtime, "container_set", side_effect=[
                        (None, None, {}, "Needs startup", {}, {}),
                        (None, None, {}, second_state, {}, {}),
                    ]), patch.object(docker_runtime, "active_server", return_value=contextlib.nullcontext()) as start:
                emit = lambda _: None
                servers = docker_runtime.list_servers(Path("/workspace"), start_if_needed=True, emit=emit)
                self.assertEqual(servers[0]["state"], "Running")
                if second_state == "Running":
                    self.assertEqual(servers[0]["id"], "fixture-b")
                    start.assert_not_called()
                else:
                    self.assertEqual(servers[0]["id"], "fixture-a")
                    start.assert_called_once_with(setups["fixture-a"], keep_running=True, emit=emit)

    def test_partial_shutdown_refuses_live_workers_and_preserves_oracle(self):
        rows = {role: {"Id": role, "State": {"Running": True}}
                for role in ("oracle", "login", "game", "planet", "connection")}
        with patch.object(docker_runtime, "docker", return_value="PID COMMAND\n1 /bin/SwgGameServer cfg"), \
                patch.object(docker_runtime, "stop_started") as stop:
            with self.assertRaisesRegex(ValueError, "SwgGameServer is still active"):
                docker_runtime.finish_incomplete_shutdown(rows)
            stop.assert_not_called()
        with patch.object(docker_runtime, "docker", return_value="PID COMMAND\n1 /bin/TaskManager"), \
                patch.object(docker_runtime, "stop_started") as stop:
            docker_runtime.finish_incomplete_shutdown(rows)
            stop.assert_called_once_with(rows, ["login", "game", "planet", "connection"])

    def test_src_selection_finds_checkout_and_persists_only_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "checkout"
            for folder in ("src/engine/server/application/CentralServer", "src/game/server/application/SwgGameServer"):
                (root / folder).mkdir(parents=True)
                (root / folder / "Makefile.am").touch()
            workspace = Path(folder) / "workspace"
            self.assertEqual(select_source(workspace, root / "src"), str(root.resolve()))
            self.assertEqual(saved_source(workspace), str(root.resolve()))
            self.assertFalse((root / "devtools").exists())
            with self.assertRaisesRegex(ValueError, "WhiteNGold server source"):
                select_source(workspace, root / "src/engine")

    def test_character_names_change_between_suites_without_changing_the_roster(self):
        preferred = {"pilot": "first", "reserve": "newcomer"}
        roster = {"first": True, "second": True, "newcomer": False}
        self.assertEqual(assign_roles(preferred, roster, ["actor"]), {"actor": "first"})
        self.assertEqual(assign_roles(preferred, roster, ["member", "pilot"]), {"member": "second", "pilot": "first"})
        self.assertEqual(assign_roles(preferred, roster, ["actor"], creation_roles={"actor"}), {"actor": "newcomer"})
        with self.assertRaisesRegex(ValueError, "needs 3 prepared test characters"):
            assign_roles(preferred, roster, ["leader", "member", "witness"])

    def test_running_server_is_reused_and_never_stopped(self):
        driver = SimpleNamespace(REPO=Path("/source"), operation_lock=lambda _: contextlib.nullcontext(),
                                 fixture=lambda _: None)
        info = (driver, Path("/tmp/test/client"), {}, "Running", {}, {})
        with patch.object(docker_runtime, "require_docker"), patch.object(docker_runtime, "container_set", return_value=info), \
                patch.object(docker_runtime, "docker") as docker:
            with docker_runtime.active_server({}, keep_running=False, emit=lambda _: None):
                pass
            docker.assert_not_called()

    def test_only_started_services_are_stopped_central_first(self):
        driver = SimpleNamespace(REPO=Path("/source"), operation_lock=lambda _: contextlib.nullcontext(),
                                 fixture=lambda _: None)
        roles = ("log", "taskmanager", "database", "chat", "local_chat", "planet", "game",
                 "connection", "metrics", "commodities", "central", "login", "oracle")
        rows = {role: {"Id": role} for role in roles}
        info = (driver, Path("/tmp/test/client"), rows, "Stopped", {}, {})
        for keep_running in (False, True):
            with patch.object(docker_runtime, "require_docker"), \
                    patch.object(docker_runtime, "container_set", return_value=info), \
                    patch.object(docker_runtime, "prepare_restart"), \
                    patch.object(docker_runtime, "recreate_games", return_value=rows) as restart, \
                    patch.object(docker_runtime, "wait_for_login"), \
                    patch.object(docker_runtime, "wait_for_preload"), patch.object(docker_runtime, "docker") as docker:
                with docker_runtime.active_server({}, keep_running=keep_running, emit=lambda _: None):
                    pass
                restart.assert_called_once()
                stops = [call.args[3:] for call in docker.call_args_list if call.args[0] == "stop"]
                if keep_running:
                    self.assertEqual(stops, [])
                else:
                    self.assertEqual(stops[:2], [("central",), ("taskmanager",)])
                    self.assertNotIn("oracle", set().union(*stops))

    def test_login_only_gate_checks_the_saved_instance(self):
        suite = {"steps": [{"action": "session", "options": {"role": "actor"}}]}
        self.assertTrue(docker_runtime.plain_login(suite))
        suite["steps"][0]["options"]["create"] = True
        self.assertFalse(docker_runtime.plain_login(suite))
        driver = SimpleNamespace(fixture=lambda _: ("project", "schema", {}),
                                 identity=lambda bot: bot,
                                 saved=lambda *_: {"scene": "dungeon1", "instance": "294"})
        scenes = [{"scene": "dungeon1", "instance": "294", "connected": "1",
                   "preload": "finished", "heartbeat_fresh": "1"}]
        wrong = [{"definition": "dungeon1", "instance": "295", "state": "running", "ready": "1"}]
        with patch.dict(sys.modules, {"inspect_client_fixture": SimpleNamespace(rows=lambda rows: rows)}), \
                patch.object(docker_runtime, "read_json", return_value={"player": "1"}), \
                patch.object(docker_runtime, "docker", side_effect=[scenes, wrong, scenes,
                              [{"definition": "dungeon1", "instance": "294", "state": "running", "ready": "1"}]]) as query, \
                patch.object(docker_runtime.time, "sleep"):
            docker_runtime.wait_for_login_hosts(driver, Path("/tmp/client"), "central", {"actor": "actor"})
            self.assertEqual(query.call_count, 4)
