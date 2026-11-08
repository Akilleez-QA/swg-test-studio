"""Hidden-window component smoke, not Windows game visual acceptance."""
import tempfile
import tkinter as tk
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from swg_test_studio.gui import Studio

with tempfile.TemporaryDirectory() as workspace:
    root = tk.Tk()
    root.withdraw()
    try:
        app = Studio(root, workspace)
        root.update_idletasks()
        assert len(app.tree.get_children()) == 8
        app.tree.selection_set("example:login_relogin")
        app.open_selected()
        assert app.current()["id"] == "login_relogin"
        assert len(app.tabs.tabs()) == 4
        app.validate()
        assert app.status.get().startswith("Valid supported suite")
        app.tree.selection_set("example:terminal_journey")
        app.open_selected()
        suite=app.current();suite['review']['approved']=False
        app.set_editor(suite);app.approve()
        assert app.current()['review']['approved'] is True
        calls = []
        app.job = lambda *args: calls.append(args)
        app.capture_ranges.set("2:5, 7:10")
        app.export_draft()
        assert calls[-1][-4:] == ("--range", "2:5", "--range", "7:10")
        app.messages.put('{"id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","state":"armed_waiting_for_server_events"}')
        app.poll()
        assert app.capture_ranges.get() == ""
        print("GUI smoke passed: library, editor, validation and four views")
    finally:
        root.destroy()
