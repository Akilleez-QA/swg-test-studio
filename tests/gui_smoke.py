"""Hidden-window component smoke, not Windows game visual acceptance."""
import tempfile
import tkinter as tk
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from swg_test_studio.backend import environment, environment_template
from swg_test_studio.collection import Collection, export_regression
from swg_test_studio.gui import Studio
from swg_test_studio.store import write_json

with tempfile.TemporaryDirectory() as workspace:
    root = tk.Tk()
    root.withdraw()
    try:
        app = Studio(root, workspace)
        root.update_idletasks()
        assert len(app.tree.get_children()) == 10
        assert app.tree.selection() == ("example:login_relogin",)
        assert "first test" in app.example_details.get()
        app.open_selected()
        assert app.current()["id"] == "login_relogin"
        assert len(app.tabs.tabs()) == 4
        app.validate()
        assert app.status.get().startswith("Valid supported suite")
        app.tree.selection_set("example:ord_round_trip")
        app.open_selected()
        form = app.configure_environment()
        profile = environment_template()
        for field, value in form.values.items():
            value.set(profile[field])
        form.values["server_checkout"].set(r"F:\SWGProjects\swg-server")
        assert form.bindings[0][0].get() == "pilot"
        form.bindings[0][1].set("tester")
        target = Path(workspace) / "environment.json"
        with patch("swg_test_studio.environment_ui.filedialog.asksaveasfilename", return_value=str(target)):
            form.save()
        loaded = environment(target)
        assert loaded["server_checkout"] == "/mnt/f/SWGProjects/swg-server"
        assert loaded["bindings"] == {"pilot": "tester"}
        assert app.env() == str(target)
        calls = []
        app.job = lambda *args: calls.append(args)
        app.preview()
        assert calls[-1] == ("plan", "ord_round_trip", "--environment", str(target))
        with patch("swg_test_studio.gui.simpledialog.askstring", return_value="my_ord_trip"):
            app.copy_example()
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
        app.messages.put('{"id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","state":"armed_waiting_for_server_events"}')
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
        app.tree.selection_set("driver:driver_unit")
        app.open_selected()
        assert app.current() == manifest
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
        assert calls[-1] == ("plan", "my_login_test", "--environment", str(target))
        batch = Path(workspace) / "batch.json"
        with patch("swg_test_studio.gui.filedialog.asksaveasfilename", return_value=str(batch)):
            app.save_batch_template()
        assert batch.is_file()
        with patch("swg_test_studio.gui.filedialog.askopenfilename", return_value=str(batch)), \
                patch("swg_test_studio.gui.simpledialog.askinteger", return_value=2):
            app.submit_batch("plan-batch")
        assert calls[-1] == ("plan-batch", "--file", str(batch), "--jobs", "2")
        print("GUI smoke passed: profile, examples, recording, collection editing and batch controls")
    finally:
        root.destroy()
