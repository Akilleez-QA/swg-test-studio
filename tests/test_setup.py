import contextlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from swg_test_studio import docker_runtime
from swg_test_studio.setup import assign_roles, saved_source, select_source


class SetupTests(unittest.TestCase):
    def test_src_selection_finds_checkout_and_persists_only_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "checkout"
            (root / "src").mkdir(parents=True)
            tools = root / "devtools/zones"
            tools.mkdir(parents=True)
            (tools / "protocol_driver.py").touch()
            workspace = Path(folder) / "workspace"
            self.assertEqual(select_source(workspace, root / "src"), str(root.resolve()))
            self.assertEqual(saved_source(workspace), str(root.resolve()))
            with self.assertRaisesRegex(ValueError, "contains src and devtools"):
                select_source(workspace, tools)

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
                 "connection", "login", "metrics", "commodities", "central", "oracle")
        rows = {role: {"Id": role} for role in roles}
        info = (driver, Path("/tmp/test/client"), rows, "Stopped", {}, {})
        for keep_running in (False, True):
            with patch.object(docker_runtime, "require_docker"), \
                    patch.object(docker_runtime, "container_set", return_value=info), \
                    patch.object(docker_runtime, "wait_for_login"), patch.object(docker_runtime, "docker") as docker:
                with docker_runtime.active_server({}, keep_running=keep_running, emit=lambda _: None):
                    pass
                starts = [call.args[1] for call in docker.call_args_list if call.args[0] == "start"]
                self.assertEqual(starts, list(roles[:-1]))
                stops = [call.args[3:] for call in docker.call_args_list if call.args[0] == "stop"]
                if keep_running:
                    self.assertEqual(stops, [])
                else:
                    self.assertEqual(stops[:2], [("central",), ("taskmanager",)])
                    self.assertNotIn("oracle", set().union(*stops))
