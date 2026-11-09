"""Hidden-window component smoke, not Windows game visual acceptance."""
import json
import tempfile
import tkinter as tk
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from swg_test_studio.collection import Collection, export_regression
from swg_test_studio.gui import Studio
from swg_test_studio.store import write_json

with tempfile.TemporaryDirectory() as workspace:
    root = tk.Tk()
    root.withdraw()
    try:
        app = Studio(root, workspace)

        def open_context(item):
            with patch.object(app.tree, "identify_row", return_value=item), patch.object(app.test_menu, "tk_popup") as popup:
                assert app.show_test_menu(SimpleNamespace(y=50, x_root=200, y_root=250)) == "break"
            if popup.called:
                popup.assert_called_once_with(200, 250)
            return popup.called

        root.update_idletasks()
        assert len(app.tree.get_children()) == 10
        assert app.tree.selection() == ("example:login_relogin",)
        assert app.tree.heading("#0", "text") == "Result"
        assert app.tree.heading("title", "text") == "Test"
        assert app.tree.set("example:login_relogin", "title") == app.library.get("login_relogin")["title"]
        assert not app.tree.item("example:login_relogin", "text")
        assert "first test" in app.example_details.get()
        app.open_selected()
        assert app.current()["id"] == "login_relogin"
        assert len(app.tabs.tabs()) == 4
        app.validate()
        assert app.status.get().startswith("Valid supported suite")
        app.tree.selection_set("example:ord_round_trip")
        app.open_selected()
        app.output.configure(state="normal")
        app.output.insert("end", "Choose the SWG source folder first.")
        app.output.configure(state="disabled")
        result = {"event": "test_servers", "source": "/mnt/f/SWGProjects/swg-server", "servers": [
            {"id": "swg-cold-test-01234567", "name": "Local SWG test server", "state": "Stopped", "characters": 1}
        ]}
        process = SimpleNamespace(stdout=[json.dumps(result)], wait=lambda: 0)
        with patch("swg_test_studio.gui.subprocess.Popen", return_value=process), \
                patch("swg_test_studio.gui.threading.Thread") as thread:
            thread.side_effect = lambda *, target, daemon: SimpleNamespace(start=target)
            app.job("select-source", "--source", r"F:\SWGProjects\swg-server\src")
        app.poll()
        assert app.status.get() == "Source folder saved. Found 1 Docker test server."
        assert app.output.get("1.0", "end").strip() == app.status.get()
        with patch("swg_test_studio.gui.subprocess.Popen", return_value=process), \
                patch("swg_test_studio.gui.threading.Thread"), \
                patch("swg_test_studio.gui.time.monotonic", return_value=100):
            login = app.job("run", "login_relogin", *app.server_argument())
        assert str(app.progress_bar.cget("mode")) == "indeterminate"
        app.messages.put((login, json.dumps({"event": "run_preparing", "cases": 2})))
        app.messages.put((login, json.dumps({"event": "case_finished", "id": "first_login", "passed": True})))
        with patch("swg_test_studio.gui.time.monotonic", return_value=162):
            app.poll()
        assert app.progress_text.get() == "Running · 1:02 elapsed · 1 of 2 cases complete"
        app.messages.put((login, json.dumps({"event": "case_finished", "id": "repeat_login", "passed": True, "seconds": 2.5})))
        app.messages.put((login, json.dumps({"event": "run_finished", "passed": True, "evidence": "/tmp/studio-result"})))
        app.messages.put((login, 0))
        with patch("swg_test_studio.gui.time.monotonic", return_value=230):
            app.poll()
        assert app.progress_text.get() == "Finished · 2:10 elapsed · 2 of 2 cases complete"
        assert str(app.progress_bar.cget("mode")) == "determinate"
        assert "Repeat login passed (2.5 seconds)." in app.output.get("1.0", "end")
        assert app.status.get() == "Test passed."
        calls = []
        submit_job = app.job
        app.job = lambda *args: calls.append(args)
        with patch("swg_test_studio.gui.filedialog.askdirectory", return_value=r"F:\SWGProjects\swg-server\src"):
            app.configure_environment()
        assert calls[-1] == ("select-source", "--source", r"F:\SWGProjects\swg-server\src")
        project = "swg-cold-test-01234567"
        app.show_servers({"source": "/mnt/f/SWGProjects/swg-server", "servers": [
            {"id": project, "name": "Local SWG test server", "state": "Stopped", "characters": 2}
        ]})
        app.preview()
        assert calls[-1] == ("plan", "ord_round_trip", "--test-server", project)
        app.keep_running.set(True)
        app.run()
        assert calls[-1] == ("run", "ord_round_trip", "--test-server", project, "--keep-running")
        assert not open_context("")
        assert app.tree.selection() == ("example:ord_round_trip",)
        app.toggle_checked("example:ord_round_trip")
        app.editor.insert("end", "\n")
        editor_text = app.editor.get("1.0", "end")
        assert open_context("example:login_relogin")
        assert app.tree.selection() == ("example:login_relogin",)
        assert app.test_menu.entrycget("Run this test", "state") == "normal"
        app.test_menu.invoke("Run this test")
        assert calls[-1] == ("run", "login_relogin", "--test-server", project, "--keep-running")
        app.test_menu.invoke("Preview run")
        assert calls[-1] == ("plan", "login_relogin", "--test-server", project)
        app.test_menu.invoke("Validate")
        assert app.status.get().startswith("Valid supported suite")
        target = Path(workspace) / "exported-login.json"
        with patch("swg_test_studio.gui.filedialog.asksaveasfilename", return_value=str(target)):
            app.test_menu.invoke("Export test…")
        assert json.loads(target.read_text(encoding="utf-8")) == app.library.get("login_relogin")
        assert app.checks() == {"example:ord_round_trip"}
        assert app.editor.get("1.0", "end") == editor_text
        app.test_menu.invoke("Check for run")
        assert open_context("example:login_relogin")
        app.test_menu.invoke("Uncheck for run")
        assert app.checks() == {"example:ord_round_trip"}
        assert open_context("example:ord_round_trip")
        app.players.set("Two players")
        app.start_recording()
        assert calls[-1] == ("record-start", "--test-server", project, "--role", "leader", "--role", "member")
        with patch("swg_test_studio.gui.simpledialog.askstring", return_value="my_ord_trip"):
            app.test_menu.invoke("Copy example…")
        assert app.current()["id"] == "my_ord_trip"
        assert app.library.get("my_ord_trip")["steps"] == app.library.get("ord_round_trip")["steps"]
        assert len(app.tree.get_children()) == 11
        (Path(workspace) / "suites" / "broken.json").write_text("{", encoding="utf-8")
        app.refresh()
        assert len(app.tree.get_children()) == 11
        assert "broken.json" in app.status.get()
        app.tree.selection_set("example:terminal_journey")
        app.open_selected()
        suite=app.current();suite['review']['approved']=False
        app.set_editor(suite);app.approve()
        assert app.current()['review']['approved'] is True
        app.capture_ranges.set("2:5, 7:10")
        app.export_draft()
        assert calls[-1][-4:] == ("--range", "2:5", "--range", "7:10")
        with patch("swg_test_studio.gui.subprocess.Popen", return_value=process), \
                patch("swg_test_studio.gui.threading.Thread"):
            recorder = submit_job("record-start", *app.server_argument(), "--role", "actor")
            app.messages.put((recorder, '{"id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","state":"armed_waiting_for_server_events"}'))
            app.messages.put((recorder, 0))
            app.poll()
        assert app.capture_ranges.get() == ""
        checkout = Path(workspace) / "server"
        manifest = {"schema_version": 1, "id": "driver_unit", "title": "Driver guards", "category": "unit",
                    "roles": [], "tests": [{"id": "unit_checks", "kind": "driver_unit", "options": {}}]}
        write_json(checkout / "devtools/zones/test_sets/driver_unit.json", manifest)
        path = export_regression(checkout, Path(workspace) / "regression.json")
        with patch("swg_test_studio.gui.filedialog.askopenfilename", return_value=str(path)):
            app.import_suite()
        assert len(app.tree.get_children()) == 11
        assert open_context("driver:driver_unit")
        labels = [app.test_menu.entrycget(index, "label") for index in range(app.test_menu.index("end") + 1)
                  if app.test_menu.type(index) != "separator"]
        assert "Run this test" not in labels
        app.test_menu.invoke("Open in editor")
        assert app.current() == manifest
        assert app.tree.set("driver:driver_unit", "kind") == "Server test"
        original = path.read_bytes()
        app.test_menu.invoke("Remove from Studio")
        assert not app.tree.exists("driver:driver_unit")
        assert path.read_bytes() == original
        app.show_removed.set(True)
        app.refresh()
        assert open_context("driver:driver_unit")
        app.test_menu.invoke("Restore to Studio")
        assert app.tree.set("driver:driver_unit", "kind") == "Server test"
        app.show_removed.set(False)
        app.validate()
        assert "driver manifest structure" in app.status.get()
        copy = Path(workspace) / "my_regression.json"
        with patch("swg_test_studio.gui.filedialog.asksaveasfilename", return_value=str(copy)):
            app.save_collection_as()
        app.new_test()
        draft = app.current()
        draft["id"] = "my_login_test"
        app.set_editor(draft)
        app.approve()
        app.save()
        app.close_collection()
        app.open_collection(copy)
        assert len(app.tree.get_children()) == 12
        assert len(Collection(path).list()) == 11
        app.tree.selection_set("studio:my_login_test")
        app.open_selected()
        assert app.current()["review"]["approved"]
        app.preview()
        assert calls[-1] == ("plan", "my_login_test", "--test-server", project)
        batch = Path(workspace) / "batch.json"
        with patch("swg_test_studio.gui.filedialog.asksaveasfilename", return_value=str(batch)):
            app.save_batch_template()
        assert batch.is_file()
        with patch("swg_test_studio.gui.filedialog.askopenfilename", return_value=str(batch)), \
                patch("swg_test_studio.gui.simpledialog.askinteger", return_value=2):
            app.submit_batch("plan-batch")
        assert calls[-1] == ("plan-batch", "--file", str(batch), "--jobs", "2")
        groups = {"Login checks": [f"login_{index:02d}" for index in range(5)],
                  "Travel checks": [f"travel_{index:02d}" for index in range(8)]}
        template = app.library.get("login_relogin")
        group_file = Collection(Path(workspace) / "groups.json")
        original = [dict(template, id=name) for members in groups.values() for name in members]
        group_file.write({"format": "swg-test-studio-collection", "schema_version": 1,
                          "title": "Grouped tests", "suites": original, "groups": groups})
        app.open_collection(group_file.path)
        app.tree.item("group:Login checks", open=False)
        app.refresh()
        assert not app.tree.item("group:Login checks", "open")
        app.toggle_checked("group:Login checks")
        assert app.tree.set("group:Login checks", "check") == "☑"
        app.toggle_checked("studio:login_00")
        app.toggle_checked("studio:login_01")
        app.toggle_checked("group:Travel checks")
        app.toggle_checked("studio:travel_00")
        assert app.tree.set("group:Login checks", "check") == "◩"
        assert app.tree.set("group:Travel checks", "check") == "◩"
        assert len(app.checks()) == 10
        assert "3/5 checked" in app.tree.set("group:Login checks", "title")
        assert "7/8 checked" in app.tree.set("group:Travel checks", "title")
        with patch.object(app.tree, "identify_row", return_value="group:Login checks"), \
                patch.object(app.tree, "identify_column", return_value="#2"):
            assert app.open_row(SimpleNamespace(x=200, y=70)) == "break"
            assert app.tree.item("group:Login checks", "open")
            assert app.open_row(SimpleNamespace(x=200, y=70)) == "break"
            assert not app.tree.item("group:Login checks", "open")
        app.run_checked()
        command = calls[-1]
        assert command[:3] == ("run-selected", "--test-server", project)
        assert [command[i + 1] for i, value in enumerate(command) if value == "--suite"] == (
            groups["Login checks"][2:] + groups["Travel checks"][1:])
        app.drag = ("studio:login_02", 10, 10)
        with patch.object(app.tree, "identify_row", return_value="group:Travel checks"):
            app.drop_row(SimpleNamespace(x=35, y=70))
        assert app.tree.parent("studio:login_02") == "group:Travel checks"
        assert "login_02" in group_file.groups()["Travel checks"]
        assert group_file.read()["suites"] == original and len(app.checks()) == 10
        assert not open_context("group:Travel checks")
        assert open_context("studio:login_02")
        assert app.move_menu.entrycget("Travel checks", "state") == "disabled"
        app.move_menu.invoke("Login checks")
        assert app.tree.parent("studio:login_02") == "group:Login checks"
        assert group_file.read()["suites"] == original and len(app.checks()) == 10

        app.job = submit_job
        with patch("swg_test_studio.gui.subprocess.Popen", return_value=process) as spawn, \
                patch("swg_test_studio.gui.threading.Thread"):
            app.run_checked()
            selection = app.current_job.get()
            assert not app.run_selected_button.instate(("disabled",))
            assert open_context("studio:login_02")
            assert app.test_menu.entrycget("Run this test", "state") == "disabled"
            app.clear_checks()
            app.toggle_checked("studio:login_00")
            app.run_checked()
            waiting = app.current_job.get()
            assert spawn.call_count == 1
            assert app.progress_text.get().startswith("Queued")
            assert app.tree.item("studio:login_00", "text") == "Queued"

            # Another verified project and source can run before the earlier queued selection.
            other_project = "swg-cold-test-89abcdef"
            app.show_servers({"source": "/mnt/f/SWGProjects/swg-other-server", "servers": [
                {"id": other_project, "name": "Second SWG test server", "state": "Running", "characters": 1}
            ]})
            other = app.job("run", "travel_00", *app.server_argument())
            assert spawn.call_count == 2
            assert app.job_counts.get() == "2 running · 1 queued"
            first_argv, other_argv = [call.args[0] for call in spawn.call_args_list]
            assert first_argv[first_argv.index("--run-workspace") + 1] != other_argv[other_argv.index("--run-workspace") + 1]
            assert app.tree.item("studio:travel_00", "text") == "Running"
            app.messages.put((selection, json.dumps({"event": "batch_job_started", "suite": "login_02"})))
            app.messages.put((other, json.dumps({"event": "error", "error": "Second run failed"})))
            app.messages.put((other, 1))
            app.poll()
            assert spawn.call_count == 2
            assert app.job_counts.get() == "1 running · 1 queued"
            assert app.tree.item("studio:travel_00", "text") == "Failed"
            assert app.tree.item("studio:login_02", "text") == "Running"
            assert app.output.get("1.0", "end").strip() == "Second run failed"
            app.current_job.set(selection)
            app.show_job()
            assert "Running login 02" in app.output.get("1.0", "end")
            assert "Second run failed" not in app.output.get("1.0", "end")
            app.messages.put((selection, json.dumps({"event": "batch_job_finished", "suite": "login_02", "passed": True})))
            failure = Path(workspace) / "failed-travel"
            write_json(failure / "manifest.json", {"tests": [{"id": name} for name in ("launch", "landing", "save")]})
            write_json(failure / "result.json", {"suite": "travel_01", "passed": False, "cases": [
                {"id": "launch", "passed": True}, {"id": "landing", "passed": False, "exit_code": 1}
            ]})
            (failure / "landing.log").write_text(
                "STUDIO_STEP start 2 land\nSCENARIO_FAILURE Expected hangar\n", encoding="utf-8")
            app.messages.put((selection, json.dumps({"event": "batch_job_finished", "suite": "travel_01",
                                                    "passed": False, "result": str(failure / "result.json")})))
            app.messages.put((selection, 1))
            app.poll()
            assert spawn.call_count == 3
            queued_argv = spawn.call_args.args[0]
            assert queued_argv[queued_argv.index("--source") + 1] == "/mnt/f/SWGProjects/swg-server"
            assert queued_argv[queued_argv.index("--test-server") + 1] == project
            app.messages.put((waiting, 1))
            app.poll()
        assert app.job_counts.get() == "0 running · 0 queued"
        assert app.tree.item("studio:login_02", "text") == "Passed"
        assert app.tree.item("studio:travel_01", "text") == "Failed"
        assert app.tree.set("studio:login_02", "title") == template["title"]
        app.suite_status[app.removal_scope()]["login_02"] = "Running"
        with patch("swg_test_studio.gui.time.monotonic", return_value=100.0):
            app.update_result_icons(running_only=True)
        first_frame = app.tree.item("studio:login_02", "image")
        with patch("swg_test_studio.gui.time.monotonic", return_value=100.25):
            app.update_result_icons(running_only=True)
        assert first_frame and app.tree.item("studio:login_02", "image") != first_frame
        app.suite_status[app.removal_scope()]["login_02"] = "Passed"
        app.update_result_icons()
        assert str(app.tree.item("studio:login_02", "image")[0]) == str(app.result_icons["Passed"])
        assert str(app.tree.item("studio:travel_01", "image")[0]) == str(app.result_icons["Failed"])
        assert open_context("studio:travel_01")
        app.test_menu.invoke("View latest result…")
        window, = (child for child in root.winfo_children() if isinstance(child, tk.Toplevel))
        frame, = window.winfo_children()
        _, panes = frame.winfo_children()
        steps, details = panes.winfo_children()
        assert steps.selection() == ("1",)
        assert [steps.set(item, "status") for item in steps.get_children()] == ["Passed", "Failed", "Not run"]
        log = next(child for child in details.winfo_children() if isinstance(child, tk.Text))
        assert "Action 2 · Land" in log.get("1.0", "end")
        assert "Expected hangar" in log.get("1.0", "end")
        assert "landing.log" in log.get("1.0", "end")
        window.destroy()
        print("GUI smoke passed: per-test failure log, context menu, grouping, concurrent runs and result icons")
    finally:
        root.destroy()
