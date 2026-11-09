"""Native local UI. No HTTP listener, browser commands or game-client patches."""
from dataclasses import dataclass, field
import json
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from .backend import local_path
from .batch import MAX_JOBS, MAX_RUNS, batch_template
from .collection import FORMAT as COLLECTION_FORMAT, MAX_BYTES, Collection, is_driver_suite, validate_entry
from .groups import UNGROUPED, group_membership, move_test, validate_groups
from .model import loads, validate
from .result_icons import icons
from .results import ResultSource, ResultStep, log_tail, open_saved_report, result_steps
from .setup import saved_source
from .store import Library, read_json, write_json


EXAMPLE_DETAILS = {
    "login_relogin": "A good first test. Log in, log out, then log in again to verify the character saved. Use an existing dedicated character.",
    "create_character": "Create a test character and verify the first login, logout and save. The test server needs one unused character slot.",
    "driver_guards": "Run the server checkout's driver unit checks. The suite has no character roles and needs no running game services.",
    "gamma_shuttle": "Use the original shuttle terminal to travel from Tansaari to Gamma and back. Start at Tansaari with an actor prepared for shuttle travel.",
    "terminal_journey": "Replay both shuttle directions in one session. The fixture positions a solo Tansaari actor near the terminals.",
    "shuttle_recorded_cases": "Replay three reviewed clips covering cancellation and both travel directions. Use a solo actor in either supported station.",
    "ord_round_trip": "Replay a recorded launch from Tansaari to Ord Mantell and land in the authored hangar. Use a solo Tansaari pilot.",
    "ord_group_sequence": "Form a group, change leaders, launch, land and disband. Needs two test characters who start solo at Tansaari.",
    "ship_and_group": "Check ship ownership, landing and group travel. Needs two test characters at Tansaari.",
    "group_disband": "Verify that former members travel independently and can join a new group. Needs three test characters on a Rryatt/Ord test server.",
}

GETTING_STARTED = (
    "1. Open the selected login and relogin example in the Library. Click Validate to inspect it offline.\n\n"
    "2. Use Copy example to make an editable test. Each test shows how many players it needs.\n\n"
    "3. Install and start Docker. Click Choose source folder and select your SWG source. "
    "Studio finds prepared Docker test servers and chooses test characters automatically. "
    "Click Find or start test server to bring up a stopped server.\n\n"
    "4. Preview run shows what the test will do. Run can start a stopped test server. "
    "You can submit more tests while a run is active. Tests that share a server wait for their turn. "
    "Use Run & Results to switch between runs. Check Keep test server running to keep it available.\n\n"
    "5. In Record, choose one or two players. After playing, stop and export a draft, "
    "review its expectations, then save it for replay."
)


@dataclass
class DesktopJob:
    argv: list
    command: str
    scope: str
    resources: set
    states: dict
    message: str
    log: list = field(default_factory=list)
    results: dict = field(default_factory=dict)
    started: float | None = None
    finished: float | None = None
    exit_code: int | None = None
    total: int = 0
    completed: int = 0
    unit: str = "cases"
    final_message: str = ""
    error: str = ""

    def conflicts(self, other):
        if "control" in self.resources and "control" in other.resources:
            return True
        if self.resources == {"control"} or other.resources == {"control"}:
            return False
        return ("exclusive" in self.resources or "exclusive" in other.resources or
                not self.resources.isdisjoint(other.resources))


class Studio:
    def __init__(self, root, workspace, collection=None):
        self.root, self.library = root, Library(workspace)
        self.messages = queue.Queue()
        self.jobs = {}
        self.current_job = tk.StringVar()
        self.job_counts = tk.StringVar(value="0 running · 0 queued")
        self.library_rows = {}
        self.group_nodes = {}
        self.checkable_rows = {}
        self.checked_tests = {}
        self.drag = None
        self.suite_status = {}
        self.result_icons = icons(root)
        self.collection = None
        self.library_title = tk.StringVar(value="Examples and saved tests")
        self.filter_text = tk.StringVar()
        self.source = tk.StringVar()
        self.source_path = None
        self.server = tk.StringVar()
        self.server_choices = {}
        self.keep_running = tk.BooleanVar(value=False)
        self.progress_text = tk.StringVar(value="No operation running")
        self.removed_path = self.library.workspace / "removed-tests.json"
        self.groups_path = self.library.workspace / "library-groups.json"
        self.show_removed = tk.BooleanVar(value=False)
        self.example_details = tk.StringVar()
        self.recording = tk.StringVar()
        self.capture_ranges = tk.StringVar()
        self.players = tk.StringVar(value="One player")
        self.status = tk.StringVar(value="Open the selected starter example and click Validate to try Studio offline.")
        root.title("SWG Test Studio")
        root.geometry("1150x760")
        root.minsize(850, 560)
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI", 21, "bold"))
        shell = ttk.Frame(root, padding=18)
        shell.pack(fill="both", expand=True)
        ttk.Label(shell, text="SWG Test Studio", style="Title.TLabel").pack(anchor="w")
        ttk.Label(shell, text="Create and record gameplay tests. Running tests uses Docker.").pack(anchor="w", pady=(3, 14))
        bar = ttk.Frame(shell)
        bar.pack(fill="x", pady=(0, 12))
        ttk.Label(bar, text="SWG source").pack(side="left")
        ttk.Entry(bar, textvariable=self.source, state="readonly").pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(bar, text="Choose source folder…", command=self.configure_environment).pack(side="left", padx=5)
        ttk.Button(bar, text="Help", command=self.help).pack(side="left")
        bar = ttk.Frame(shell)
        bar.pack(fill="x", pady=(0, 12))
        ttk.Label(bar, text="Docker test server").pack(side="left")
        self.server_menu = ttk.Combobox(bar, textvariable=self.server, state="readonly", width=56)
        self.server_menu.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(bar, text="Find or start test server", command=lambda: self.job("test-servers", "--start")).pack(side="left")
        ttk.Checkbutton(bar, text="Keep test server running", variable=self.keep_running).pack(side="left", padx=8)
        self.tabs = ttk.Notebook(shell)
        self.tabs.pack(fill="both", expand=True)
        library = ttk.Frame(self.tabs, padding=10)
        editor = ttk.Frame(self.tabs, padding=10)
        recording = ttk.Frame(self.tabs, padding=10)
        results = ttk.Frame(self.tabs, padding=10)
        for frame, name in ((library, "Library"), (editor, "Edit"), (recording, "Record"), (results, "Run & Results")):
            self.tabs.add(frame, text=name)
        ttk.Label(library, textvariable=self.library_title, font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Label(library, wraplength=760, text=(
            "Open an example and click Validate to explore it offline. "
            "Open a regression collection to edit and save its tests in one JSON file."
        )).pack(anchor="w", pady=(3, 8))
        search = ttk.Frame(library)
        search.pack(fill="x", pady=(0, 6))
        ttk.Label(search, text="Find a test").pack(side="left")
        filter_box = ttk.Entry(search, textvariable=self.filter_text, width=36)
        filter_box.pack(side="left", padx=6)
        filter_box.bind("<KeyRelease>", lambda _: self.refresh())
        listing = ttk.Frame(library)
        listing.pack(fill="both", expand=True)
        # Tk attaches row images to the tree column. Keep that column dedicated to results.
        self.tree = ttk.Treeview(listing, columns=("check", "title", "kind", "roles"), show=("tree", "headings"))
        for name, text, width in (("#0", "Result", 118), ("check", "Run", 55), ("title", "Test", 510),
                                  ("kind", "Test type", 125), ("roles", "Test characters", 125)):
            self.tree.heading(name, text=text)
            self.tree.column(name, width=width)
        self.tree.column("check", anchor="center", stretch=False)
        self.tree.column("#0", stretch=False)
        scrollbar = ttk.Scrollbar(listing, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", self.open_row)
        self.tree.bind("<<TreeviewSelect>>", self.show_details)
        self.tree.bind("<ButtonPress-1>", self.press_row)
        self.tree.bind("<B1-Motion>", self.drag_row)
        self.tree.bind("<ButtonRelease-1>", self.drop_row)
        self.tree.bind("<space>", lambda _: self.toggle_checked(self.tree.focus()))
        self.test_menu = tk.Menu(self.tree, tearoff=False)
        self.move_menu = tk.Menu(self.test_menu, tearoff=False)
        self.tree.bind("<Button-3>", self.show_test_menu)
        self.tree.bind("<Shift-F10>", lambda event: self.show_test_menu(event, keyboard=True))
        self.tree.bind("<Menu>", lambda event: self.show_test_menu(event, keyboard=True))
        ttk.Label(library, textvariable=self.example_details, wraplength=760).pack(anchor="w", pady=(8, 0))
        actions = ttk.Frame(library)
        actions.pack(fill="x", pady=8)
        for text, callback in (("Open", self.open_selected), ("Refresh", self.refresh),
                               ("Import JSON…", self.import_suite), ("New test", self.new_test)):
            ttk.Button(actions, text=text, command=callback).pack(side="left", padx=(0, 6))
        self.copy_button = ttk.Button(actions, text="Copy example…", command=self.copy_example)
        self.copy_button.pack(side="left")
        self.save_collection_button = ttk.Button(actions, text="Save collection as…", command=self.save_collection_as)
        self.save_collection_button.pack(side="left", padx=6)
        self.close_collection_button = ttk.Button(actions, text="Close collection", command=self.close_collection)
        self.close_collection_button.pack(side="left")
        removal = ttk.Frame(library)
        removal.pack(fill="x")
        self.remove_button = ttk.Button(removal, text="Remove from Studio", command=self.toggle_removed)
        self.remove_button.pack(side="left")
        ttk.Checkbutton(removal, text="Show removed tests", variable=self.show_removed,
                        command=self.refresh).pack(side="left", padx=8)
        groups = ttk.Frame(library)
        groups.pack(fill="x", pady=(6, 0))
        for text, callback in (("New group…", self.add_group), ("Rename group…", self.rename_group),
                               ("Remove group", self.remove_group), ("Clear checks", self.clear_checks)):
            ttk.Button(groups, text=text, command=callback).pack(side="left", padx=(0, 6))
        self.run_selected_button = ttk.Button(groups, text="Run selected (0)", command=self.run_checked)
        self.run_selected_button.pack(side="right")
        ttk.Label(library, text="Check tests to run together. Right-click a test for actions, or drag it to another group.").pack(anchor="w")
        ttk.Label(editor, text="Edit the typed JSON below. Give example copies a new ID. Each session includes logout and full save checks.").pack(anchor="w")
        self.editor = tk.Text(editor, wrap="none", undo=True, font=("Consolas", 11))
        self.editor.pack(fill="both", expand=True, pady=8)
        row = ttk.Frame(editor)
        row.pack(fill="x")
        for text, callback in (("Validate", self.validate), ("Approve reviewed expectations", self.approve), ("Save", self.save), ("Export test…", self.export_test), ("Preview run", self.preview), ("Run", self.run)):
            ttk.Button(row, text=text, command=callback).pack(side="left", padx=(0, 6))
        ttk.Label(recording, wraplength=760, text=(
            "Choose how many players to record. Studio assigns their test characters automatically. "
            "Recording keeps the Docker test server running while you play. Stop and export a draft to review it."
        )).pack(anchor="w", pady=(0, 12))
        row = ttk.Frame(recording)
        row.pack(fill="x")
        ttk.Label(row, text="Players to record").pack(side="left")
        ttk.Combobox(row, textvariable=self.players, values=("One player", "Two players"),
                     state="readonly", width=18).pack(side="left", padx=6)
        ttk.Button(row, text="Start recording", command=self.start_recording).pack(side="left")
        row = ttk.Frame(recording)
        row.pack(fill="x", pady=10)
        ttk.Label(row, text="Recording ID").pack(side="left")
        ttk.Entry(row, textvariable=self.recording, width=43).pack(side="left", padx=6)
        for text, callback in (("Refresh timeline", lambda: self.job("record-status", "--recording", self.recording.get())),
                               ("Stop", lambda: self.job("record-stop", "--recording", self.recording.get())),
                               ("Export draft", self.export_draft)):
            ttk.Button(row, text=text, command=callback).pack(side="left", padx=3)
        row = ttk.Frame(recording)
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, text="Optional clips (first:last, comma-separated; blank uses all events)").pack(side="left")
        ttk.Entry(row, textvariable=self.capture_ranges).pack(side="left", fill="x", expand=True, padx=6)
        self.timeline = tk.Text(recording, wrap="none", font=("Consolas", 10), state="disabled")
        self.timeline.pack(fill="both", expand=True)
        ttk.Label(results, text="CLI events and evidence locations. A protocol pass does not establish Windows visual acceptance.").pack(anchor="w")
        batch_actions = ttk.Frame(results)
        batch_actions.pack(fill="x", pady=(6, 0))
        for text, action in (("Save batch template…", self.save_batch_template),
                             ("Preview batch…", lambda: self.submit_batch("plan-batch")),
                             ("Run batch…", lambda: self.submit_batch("run-batch")),
                             ("Check Studio in Docker", lambda: self.job("docker-check"))):
            ttk.Button(batch_actions, text=text, command=action).pack(side="left", padx=(0, 6))
        ttk.Label(results, wraplength=900, text=(
            "You can start more tests while a run is active. Tests sharing a Docker test server or source checkout "
            "wait for the earlier run to finish. Select a run below to see its progress and results."
        )).pack(anchor="w", pady=(6, 0))
        run_picker = ttk.Frame(results)
        run_picker.pack(fill="x", pady=(6, 0))
        ttk.Label(run_picker, text="Run").pack(side="left")
        self.job_menu = ttk.Combobox(run_picker, textvariable=self.current_job, state="readonly")
        self.job_menu.pack(side="left", fill="x", expand=True, padx=8)
        self.job_menu.bind("<<ComboboxSelected>>", lambda _: self.show_job())
        ttk.Label(run_picker, textvariable=self.job_counts).pack(side="left")
        report_actions = ttk.Frame(results)
        report_actions.pack(fill="x", pady=(6, 0))
        ttk.Button(report_actions, text="View test results…", command=self.view_run_results).pack(side="left")
        ttk.Button(report_actions, text="Open saved report…", command=self.open_result_report).pack(side="left", padx=6)
        self.output = tk.Text(results, wrap="word", font=("Consolas", 10), state="disabled")
        self.output.pack(fill="both", expand=True, pady=8)
        status_row = ttk.Frame(shell)
        status_row.pack(fill="x", pady=(10, 0))
        self.status_icon = ttk.Label(status_row)
        self.status_icon.pack(side="left", padx=(0, 4))
        ttk.Label(status_row, textvariable=self.status, wraplength=1020).pack(side="left")
        progress = ttk.Frame(shell)
        progress.pack(fill="x", pady=(6, 0))
        self.progress_bar = ttk.Progressbar(progress, mode="determinate")
        self.progress_bar.pack(side="left", fill="x", expand=True)
        ttk.Label(progress, textvariable=self.progress_text).pack(side="left", padx=(10, 0))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()
        if collection:
            self.guarded(lambda: self.open_collection(collection))
        try:
            source = saved_source(self.library.workspace)
            if source:
                self.source_path = source
                self.source.set(str(local_path(source)))
                self.job("test-servers")
        except (ValueError, OSError):
            self.status.set("Choose the SWG source folder again to update the saved selection.")
        root.after(100, self.poll)

    def guarded(self, callback):
        try:
            return callback()
        except Exception as exc:
            self.status.set(str(exc))
            messagebox.showerror("SWG Test Studio", str(exc), parent=self.root)

    def refresh(self):
        def action():
            selected = self.tree.selection()
            invalid = []
            if self.collection:
                rows = self.collection.list()
                self.library_title.set(f"{self.collection.path.stem} ({len(rows)} suites)")
            else:
                rows = self.library.list(on_invalid_saved_test=lambda path, exc: invalid.append(path.name))
            needle = self.filter_text.get().strip().casefold()
            removed = self.removed_tests().get(self.removal_scope(), [])
            groups = self.test_groups()
            membership = group_membership(groups)
            opened = {group: self.tree.item(item, "open") for item, group in self.group_nodes.items()
                      if self.tree.exists(item)}
            self.tree.delete(*self.tree.get_children())
            self.library_rows = {}
            self.group_nodes = {}
            self.checkable_rows = {}
            if groups:
                ordered = {name: index for index, name in enumerate((*groups, UNGROUPED))}
                rows.sort(key=lambda row: ordered[membership.get(row["id"], UNGROUPED)])
                for group in ordered:
                    item = "group:" + group
                    self.group_nodes[item] = group
                    self.tree.insert("", "end", iid=item, values=("", group), open=opened.get(group, True))
            for row in rows:
                item = row["origin"] + ":" + row["id"]
                group = membership.get(row["id"], UNGROUPED)
                if row["origin"] != "driver" and item not in removed:
                    self.checkable_rows[item] = (group, row["id"])
                if needle and needle not in (row["id"] + " " + row["title"]).casefold():
                    continue
                if item in removed and not self.show_removed.get():
                    continue
                self.library_rows[item] = row
                origin = {"example": "Example", "user": "Studio test", "studio": "Studio test",
                          "driver": "Server test"}[row["origin"]]
                if item in removed:
                    origin += " (removed)"
                self.tree.insert("group:" + group if groups else "", "end", iid=item,
                                 values=("", row["title"], origin, len(row["roles"])))
            starter = "studio:login_relogin" if self.collection else "example:login_relogin"
            item = selected[0] if selected and self.tree.exists(selected[0]) else starter
            if not self.tree.exists(item) and self.library_rows:
                item = next(iter(self.library_rows))
            if self.tree.exists(item):
                self.tree.selection_set(item)
                if not selected or selected[0] != item:
                    self.tree.see(item)
            self.show_details()
            self.update_checks()
            self.update_result_icons()
            state = "normal" if self.collection else "disabled"
            self.save_collection_button.configure(state=state)
            self.close_collection_button.configure(state=state)
            if invalid:
                names = ", ".join(invalid[:3]) + (" and others" if len(invalid) > 3 else "")
                self.status.set("Skipped invalid saved test files: " + names)
        self.guarded(action)

    def selected_row(self):
        selection = self.tree.selection()
        return self.library_rows.get(selection[0]) if selection else None

    def show_details(self, _event=None):
        row = self.selected_row()
        example = row and row["origin"] == "example"
        self.copy_button.configure(state="normal" if example else "disabled")
        removed = self.removed_tests().get(self.removal_scope(), [])
        self.remove_button.configure(state="normal" if row else "disabled",
                                     text="Restore to Studio" if self.tree.selection() and
                                     self.tree.selection()[0] in removed else "Remove from Studio")
        if row:
            if row["origin"] == "driver":
                notes = "This test runs with the SWG server’s existing test tools. You can open or export it here."
            else:
                notes = EXAMPLE_DETAILS.get(row["id"], "Open this test to inspect its steps and expected results.")
            roles = ", ".join(row["roles"])
            explanation = (f"\nThe test calls its players {roles}. These names describe their parts in the test. "
                           "Studio assigns the actual test characters automatically." if roles and row["origin"] != "driver" else "")
            self.example_details.set(notes + explanation)
        else:
            self.example_details.set("Check a group to select all its Studio tests, or check individual tests across groups.")

    def test_groups(self):
        if self.collection:
            return self.collection.groups()
        return validate_groups(read_json(self.groups_path)) if self.groups_path.is_file() else {}

    def save_groups(self, groups):
        validate_groups(groups)
        if self.collection:
            self.collection.save_groups(groups)
        else:
            write_json(self.groups_path, groups, replace=True)
        self.refresh()

    def selected_group(self):
        selection = self.tree.selection()
        return self.group_nodes.get(selection[0]) if selection else None

    def add_group(self):
        def action():
            name = simpledialog.askstring("New group", "Name the group.", parent=self.root)
            if name is not None:
                groups = self.test_groups()
                name = name.strip()
                if name in groups:
                    raise ValueError("A group with that name already exists.")
                self.save_groups({**groups, name: []})
                self.tree.selection_set("group:" + name)
        self.guarded(action)

    def rename_group(self):
        def action():
            old = self.selected_group()
            if old is None or old == UNGROUPED:
                raise ValueError("Select a named group first.")
            name = simpledialog.askstring("Rename group", "Enter the new name.", initialvalue=old, parent=self.root)
            if name is not None:
                groups = self.test_groups()
                name = name.strip()
                if name != old and name in groups:
                    raise ValueError("A group with that name already exists.")
                self.save_groups({name if key == old else key: tests for key, tests in groups.items()})
                self.tree.selection_set("group:" + name)
        self.guarded(action)

    def remove_group(self):
        def action():
            group = self.selected_group()
            if group is None or group == UNGROUPED:
                raise ValueError("Select a named group first.")
            if messagebox.askyesno("Remove group", "Move this group’s tests to Ungrouped?", parent=self.root):
                groups = self.test_groups()
                del groups[group]
                self.save_groups(groups)
        self.guarded(action)

    def open_row(self, event):
        item = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if column == "#1":
            return "break"
        if column == "#2" and item in self.group_nodes:
            self.tree.item(item, open=not self.tree.item(item, "open"))
            return "break"
        if item in self.library_rows:
            self.open_selected()

    def show_test_menu(self, event, *, keyboard=False):
        item = self.tree.focus() if keyboard else self.tree.identify_row(event.y)
        if item not in self.library_rows:
            return "break"
        if keyboard:
            bounds = self.tree.bbox(item, "title")
            if not bounds:
                return "break"
            x, y, _, height = bounds
            position = self.tree.winfo_rootx() + x, self.tree.winfo_rooty() + y + height
        else:
            position = event.x_root, event.y_root
        self.tree.selection_set(item)
        self.tree.focus(item)
        self.tree.focus_set()
        self.guarded(lambda: self.post_test_menu(item, position))
        return "break"

    def post_test_menu(self, item, position):
        menu = self.test_menu
        menu.delete(0, "end")
        row = self.library_rows[item]
        removed = item in self.removed_tests().get(self.removal_scope(), [])
        latest = self.latest_test_job(row["id"])
        if latest:
            menu.add_command(label="View latest result…",
                             command=lambda: self.view_run_results(latest, row["id"]))
            menu.add_separator()
        if item in self.checkable_rows:
            busy = row["id"] in self.scheduled_tests(self.removal_scope())
            menu.add_command(label="Run this test", command=lambda: self.run(item),
                             state="disabled" if busy else "normal")
            menu.add_command(label="Preview run", command=lambda: self.preview(item))
            menu.add_separator()
        menu.add_command(label="Open in editor", command=lambda: self.open_selected(item))
        menu.add_command(label="Validate", command=lambda: self.validate(item))
        if row["origin"] == "example":
            menu.add_command(label="Copy example…", command=lambda: self.copy_example(item))
        menu.add_command(label="Export test…", command=lambda: self.export_test(item))
        menu.add_separator()
        if item in self.checkable_rows:
            label = "Uncheck for run" if item in self.checks() else "Check for run"
            menu.add_command(label=label, command=lambda: self.toggle_checked(item))
        groups = self.test_groups()
        if groups and not removed:
            current = group_membership(groups).get(row["id"], UNGROUPED)
            self.move_menu.delete(0, "end")
            for group in (*groups, UNGROUPED):
                self.move_menu.add_command(label=group, state="disabled" if group == current else "normal",
                                           command=lambda name=group: self.guarded(lambda: self.move_row(item, name)))
            menu.add_cascade(label="Move to group", menu=self.move_menu)
        menu.add_command(label="Restore to Studio" if removed else "Remove from Studio",
                         command=lambda: self.toggle_removed(item))
        try:
            menu.tk_popup(*position)
        finally:
            menu.grab_release()

    def press_row(self, event):
        item = self.tree.identify_row(event.y)
        self.drag = None
        if self.tree.identify_column(event.x) == "#1":
            return self.toggle_checked(item)
        if self.group_nodes and item in self.library_rows and not event.state & 5:
            self.drag = (item, event.x, event.y)

    def drag_row(self, event):
        if self.drag and abs(event.x - self.drag[1]) + abs(event.y - self.drag[2]) >= 6:
            self.tree.configure(cursor="hand2")
            if event.y < 24:
                self.tree.yview_scroll(-1, "units")
            elif event.y > self.tree.winfo_height() - 18:
                self.tree.yview_scroll(1, "units")

    def drop_row(self, event):
        drag, self.drag = self.drag, None
        self.tree.configure(cursor="")
        if not drag or abs(event.x - drag[1]) + abs(event.y - drag[2]) < 6:
            return
        target = self.tree.identify_row(event.y)
        group = self.group_nodes.get(target) or self.group_nodes.get(self.tree.parent(target) if target else "")
        if group:
            self.guarded(lambda: self.move_row(drag[0], group))

    def move_row(self, item, group):
        groups = self.test_groups()
        suite = self.library_rows[item]["id"]
        if group_membership(groups).get(suite, UNGROUPED) != group:
            self.save_groups(move_test(groups, suite, group))
            self.tree.selection_set(item)
            self.tree.see(item)

    def checks(self):
        return self.checked_tests.setdefault(self.removal_scope(), set())

    def update_checks(self):
        checked = self.checks()
        checked.intersection_update(self.checkable_rows)
        for item in self.library_rows:
            self.tree.set(item, "check", ("☑" if item in checked else "☐") if item in self.checkable_rows else "—")
        for item, group in self.group_nodes.items():
            members = {key for key, (name, _) in self.checkable_rows.items() if name == group}
            count = len(members & checked)
            self.tree.set(item, "check", "☑" if count and count == len(members) else "◩" if count else "☐")
            self.tree.set(item, "title", f"{group}  ({count}/{len(members)} checked)" if count else group)
        self.run_selected_button.configure(text=f"Run selected ({len(checked)})",
                                           state="normal" if checked else "disabled")

    def toggle_checked(self, item):
        if item in self.group_nodes:
            group = self.group_nodes[item]
            members = {key for key, (name, _) in self.checkable_rows.items() if name == group}
        else:
            members = {item} if item in self.checkable_rows else set()
        checked = self.checks()
        if members <= checked:
            checked.difference_update(members)
        else:
            checked.update(members)
        self.update_checks()
        return "break"

    def clear_checks(self):
        self.checks().clear()
        self.update_checks()

    def run_checked(self):
        def action():
            checked = self.checks()
            busy = self.scheduled_tests(self.removal_scope())
            names = [suite for key, (_, suite) in self.checkable_rows.items() if key in checked and suite not in busy]
            if checked and not names:
                self.status.set("Those tests are already running or queued.")
                return
            if not 1 <= len(names) <= MAX_RUNS:
                raise ValueError(f"Check between 1 and {MAX_RUNS} Studio tests.")
            args = ["run-selected", *self.server_argument()]
            if self.keep_running.get():
                args.append("--keep-running")
            for name in names:
                args.extend(("--suite", name))
            self.tabs.select(3)
            self.job(*args)
        self.guarded(action)

    def copy_example(self, item=None):
        def action():
            row = self.selected_row() if item is None else self.library_rows.get(item)
            if not row or row["origin"] != "example":
                return
            suite = validate(read_json(row["path"]))
            name = simpledialog.askstring("Copy example", "Enter a new test ID using lowercase letters, digits and underscores.",
                                          initialvalue=suite["id"] + "_copy", parent=self.root)
            if name is None:
                return
            suite["id"] = name.strip()
            self.library.save(suite)
            self.refresh()
            self.tree.selection_set("user:" + suite["id"])
            self.set_editor(suite)
            self.status.set("Example copied to My tests. Edit the steps, then validate and save.")
        self.guarded(action)

    def help(self):
        messagebox.showinfo("Getting started with SWG Test Studio", GETTING_STARTED, parent=self.root)

    def removal_scope(self):
        return str(self.collection.path) if self.collection else "workspace"

    def removed_tests(self):
        return read_json(self.removed_path) if self.removed_path.is_file() else {}

    def toggle_removed(self, item=None):
        def action():
            selection = self.tree.selection() if item is None else (item,)
            if not selection or selection[0] not in self.library_rows:
                return
            target = selection[0]
            removed = self.removed_tests()
            scope = self.removal_scope()
            items = removed.setdefault(scope, [])
            if target in items:
                items.remove(target)
                self.status.set("Test restored to Studio.")
            else:
                items.append(target)
                self.status.set("Test removed from Studio. Turn on Show removed tests to restore it.")
            if not items:
                removed.pop(scope)
            write_json(self.removed_path, removed, replace=True)
            self.refresh()
        self.guarded(action)

    def set_editor(self, value):
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", json.dumps(value, indent=2, ensure_ascii=False))
        self.tabs.select(1)

    def open_selected(self, item=None):
        row = self.selected_row() if item is None else self.library_rows.get(item)
        if row:
            self.guarded(lambda: self.set_editor(self.library_suite(row)))

    def library_suite(self, row):
        return self.collection.get(row["id"]) if self.collection else validate_entry(read_json(row["path"]))

    def current(self):
        return validate_entry(loads(self.editor.get("1.0", "end")))

    def studio_suite(self):
        suite = self.current()
        if is_driver_suite(suite):
            raise ValueError("Driver manifests use the original server harness. Select a Studio test for replay.")
        return suite

    def validate(self, item=None):
        def action():
            suite = self.current() if item is None else self.library_suite(self.library_rows[item])
            if is_driver_suite(suite):
                self.status.set("Valid driver manifest structure. The server harness validates case options before execution.")
            else:
                validate(suite, runnable=True)
                self.status.set("Valid supported suite. Preview checks environment bindings before Run.")
        self.guarded(action)

    def approve(self):
        def action():
            suite = self.studio_suite()
            if suite["review"]["unsupported"]:
                raise ValueError("Resolve the listed unsupported actions before approval")
            suite["review"]["approved"] = True
            validate(suite, runnable=True)
            self.set_editor(suite)
            self.status.set("Expectations marked reviewed. Save, then preview the explicit setup and run.")
        self.guarded(action)

    def save(self):
        def action():
            suite = self.current()
            library = self.collection or self.library
            if self.collection:
                replace = any(row["id"] == suite["id"] for row in self.collection.list())
            else:
                replace = (self.library.workspace / "suites" / (suite["id"] + ".json")).exists()
            if replace and not messagebox.askyesno("Replace saved test?", "Replace " + suite["id"] + "?", parent=self.root):
                return
            library.save(suite, replace=replace)
            self.refresh()
            self.status.set("Saved " + suite["id"])
        self.guarded(action)

    def import_suite(self):
        path = filedialog.askopenfilename(parent=self.root, filetypes=[("Studio test or collection JSON", "*.json")])
        if path:
            def action():
                data = read_json(path, max_bytes=MAX_BYTES)
                if isinstance(data, dict) and data.get("format") == COLLECTION_FORMAT:
                    self.open_collection(path)
                else:
                    self.set_editor(validate_entry(data))
            self.guarded(action)

    def open_collection(self, path):
        collection = Collection(path)
        collection.read()
        self.collection = collection
        self.filter_text.set("")
        self.refresh()
        self.editor.delete("1.0", "end")
        self.tabs.select(0)
        self.status.set("Opened " + str(collection.path))

    def close_collection(self):
        self.collection = None
        self.library_title.set("Examples and saved tests")
        self.filter_text.set("")
        self.editor.delete("1.0", "end")
        self.refresh()

    def save_collection_as(self):
        def action():
            target = filedialog.asksaveasfilename(parent=self.root, defaultextension=".json",
                                                  initialfile=self.collection.path.name,
                                                  filetypes=[("Studio collection JSON", "*.json")])
            if target:
                Collection(target).write(self.collection.read(), replace=Path(target).exists())
                self.open_collection(target)
        self.guarded(action)

    def new_test(self):
        self.set_editor({
            "format": "swg-test-studio", "schema_version": 1, "id": "new_test",
            "title": "New login and save test", "category": "functional", "roles": ["actor"],
            "steps": [{"id": "login_save", "action": "session", "options": {"role": "actor"}}],
            "review": {"approved": False, "recording": None, "unsupported": []},
        })
        self.status.set("Choose a unique ID, edit the test, then review and save it.")

    def export_test(self, item=None):
        def action():
            suite = self.current() if item is None else self.library_suite(self.library_rows[item])
            path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".json",
                                                initialfile=suite["id"] + ".json", filetypes=[("Test JSON", "*.json")])
            if path:
                if self.collection and Path(path).resolve() == self.collection.path.resolve():
                    raise ValueError("Choose a different filename for the individual test")
                write_json(path, suite, replace=Path(path).exists())
                self.status.set("Exported " + path)
        self.guarded(action)

    def configure_environment(self):
        path = filedialog.askdirectory(parent=self.root, title="Choose the SWG source folder",
                                      initialdir=self.source.get() or None)
        if path:
            self.job("select-source", "--source", path)

    def server_argument(self):
        if not self.source.get():
            raise ValueError("Choose the SWG source folder first.")
        project = self.server_choices.get(self.server.get())
        if not project:
            raise ValueError("Click Find or start test server, then choose a Docker test server.")
        return ("--test-server", project)

    def show_servers(self, result):
        source = result.get("source")
        previous = self.server_choices.get(self.server.get()) if not source else None
        if source:
            self.source_path = source
            self.source.set(str(local_path(source)))
        self.server_choices = {}
        for row in result["servers"]:
            label = f"{row['name']} [{row['id']}] • {row['state']} • {row['characters']} prepared players"
            self.server_choices[label] = row["id"]
        choices = list(self.server_choices)
        self.server_menu.configure(values=choices)
        selection = next((label for label in choices if self.server_choices[label] == previous), "")
        self.server.set(selection or (choices[0] if choices else ""))
        message = result.get("message")
        if not message:
            count = len(choices)
            message = f"Found {count} Docker test {'server' if count == 1 else 'servers'}."
        return ("Source folder saved. " if source else "") + message

    def preview(self, item=None):
        self.guarded(lambda: self.submit_suite("plan", item))

    def run(self, item=None):
        self.guarded(lambda: self.submit_suite("run", item))

    def submit_suite(self, command, item=None):
        if item is None:
            suite = self.studio_suite()
            try:
                existing = (self.collection or self.library).get(suite["id"])
            except ValueError:
                existing = None
            if existing != suite:
                raise ValueError("Save your test before previewing or running it")
        else:
            suite = self.library_suite(self.library_rows[item])
        validate(suite, runnable=True)
        server = self.server_argument()
        self.tabs.select(3)
        keep = ("--keep-running",) if command == "run" and self.keep_running.get() else ()
        self.job(command, suite["id"], *server, *keep)

    def start_recording(self):
        def action():
            arguments = ["record-start", *self.server_argument()]
            for role in ("actor",) if self.players.get() == "One player" else ("leader", "member"):
                arguments.extend(("--role", role))
            self.job(*arguments)
        self.guarded(action)

    def export_draft(self):
        clips = [value.strip() for value in self.capture_ranges.get().split(",") if value.strip()]
        extra = [item for value in clips for item in ("--range", value)]
        self.job("record-draft", "--recording", self.recording.get(), "--id", "recorded_test",
                 "--title", "Recorded gameplay - review required", *extra)

    def save_batch_template(self):
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".json",
                                            initialfile="studio-batch.json", filetypes=[("Batch JSON", "*.json")])
        if path:
            def action():
                write_json(path, batch_template(), replace=Path(path).exists())
                self.status.set("Saved batch template. Edit the suite IDs and environment filenames before running.")
            self.guarded(action)

    def submit_batch(self, command):
        path = filedialog.askopenfilename(parent=self.root, filetypes=[("Batch JSON", "*.json")])
        if path:
            jobs = simpledialog.askinteger("Parallel workers", "How many independent suites may run at once?",
                                           parent=self.root, initialvalue=2, minvalue=1, maxvalue=MAX_JOBS)
            if jobs is not None:
                self.job(command, "--file", path, "--jobs", str(jobs))

    def scheduled_tests(self, scope):
        return {name for job in self.jobs.values() if job.exit_code is None and job.scope == scope
                for name in job.states}

    def job(self, *args):
        command = args[0]
        launcher = Path(__file__).with_name("entry.py")
        workspace = self.library.workspace
        argv = [sys.executable, str(launcher), "--workspace", str(workspace)]
        collection = self.collection.path if self.collection else None
        scope = self.removal_scope()
        states = {}
        resources = {"control"}
        title = command.replace("-", " ").capitalize()
        if command in ("run", "run-selected"):
            names = [args[1]] if command == "run" else [
                args[index + 1] for index, arg in enumerate(args) if arg == "--suite"]
            if self.scheduled_tests(scope).intersection(names):
                self.status.set("Those tests are already running or queued.")
                return
            suites = [(self.collection or self.library).get(name) for name in names]
            # Studio's validated recipes without character roles run driver unit tests only.
            for suite in suites:
                validate(suite, runnable=True)
            resources = set()
            if any(suite["roles"] for suite in suites):
                project = args[args.index("--test-server") + 1]
                resources = {("checkout", self.source_path), ("project", project)}
            run_folder = workspace / "desktop-runs" / secrets.token_hex(16)
            snapshot = Collection(run_folder / "suite-collection.json")
            snapshot.write({"format": COLLECTION_FORMAT, "schema_version": 1,
                            "title": "Desktop run snapshot", "suites": suites})
            collection = snapshot.path
            argv.extend(("--run-workspace", str(run_folder)))
            args += ("--source", self.source_path)
            states = dict.fromkeys(names, "Queued")
            title = suites[0]["title"] if len(suites) == 1 else f"{len(suites)} selected tests"
        elif command == "run-batch":
            # The CLI batch can use several fixtures and allocates its own worker pool.
            resources = {"exclusive"}
            argv.extend(("--run-workspace", str(workspace / "desktop-runs" / secrets.token_hex(16))))
        elif command == "test-servers" and "--start" in args:
            resources = {"control", "exclusive"}
        elif command.startswith("record-") or command == "docker-check":
            resources = {"exclusive"}
            if command == "record-start":
                args += ("--source", self.source_path)
        if collection and command in ("plan", "run", "run-selected", "plan-batch", "run-batch"):
            argv.extend(("--collection", str(collection)))
        label = f"{len(self.jobs) + 1}. {title}"
        job = DesktopJob(argv + list(args), command, scope, resources, states, "Queued",
                         total=len(states) if command == "run-selected" else 0,
                         unit="tests" if command == "run-selected" else "cases")
        self.jobs[label] = job
        self.suite_status.setdefault(scope, {}).update(states)
        self.job_menu.configure(values=tuple(self.jobs))
        self.current_job.set(label)
        self.start_jobs()
        self.show_job()
        return label

    def start_jobs(self):
        active = [job for job in self.jobs.values() if job.started is not None and job.exit_code is None]
        reserved = list(active)
        for label, job in self.jobs.items():
            if job.started is not None or job.exit_code is not None:
                continue
            if any(job.conflicts(other) for other in reserved):
                job.message = "Queued · waiting for an earlier operation using the same resources."
            elif len(active) >= MAX_JOBS:
                job.message = "Queued · waiting for a worker."
            else:
                self.start_job(label, job)
                if job.exit_code is None:
                    active.append(job)
            if job.exit_code is None:
                reserved.append(job)
        queued = sum(job.started is None and job.exit_code is None for job in self.jobs.values())
        self.job_counts.set(f"{len(active)} running · {queued} queued")

    def start_job(self, label, job):
        job.started = time.monotonic()
        job.message = {
            "select-source": "Checking the source folder",
            "test-servers": "Finding Docker test servers",
            "plan": "Checking the selected test",
            "run": "Preparing the test",
            "run-selected": "Preparing the checked tests",
        }.get(job.command, "Running " + job.command) + "…"
        if job.command == "run":
            self.mark_test(job, next(iter(job.states)), "Running")
        try:
            process = subprocess.Popen(job.argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding="utf-8", errors="replace")
        except OSError as exc:
            job.final_message = str(exc)
            job.log.append(job.final_message + "\n")
            self.finish_job(job, 1)
            return

        def read():
            try:
                for line in process.stdout:
                    self.messages.put((label, line))
            finally:
                self.messages.put((label, process.wait()))
        threading.Thread(target=read, daemon=True).start()

    def show_job(self):
        job = self.jobs.get(self.current_job.get())
        if job is None:
            return
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", "".join(job.log))
        self.output.see("end")
        self.output.configure(state="disabled")
        self.status.set(job.message)
        self.update_progress()
        self.update_result_icons()

    def latest_test_job(self, suite):
        for label, job in reversed(self.jobs.items()):
            if job.scope == self.removal_scope() and (
                    any(result["suite"] == suite for result in job.results.values()) or
                    job.exit_code is not None and suite in job.states):
                return label
        return None

    def view_run_results(self, label=None, suite=None):
        def action():
            job = self.jobs.get(label or self.current_job.get())
            if job is None or (not job.results and job.exit_code is None):
                self.status.set("Choose a run with results to view.")
                return
            sources = {}
            for name, value in sorted(job.results.items(), key=lambda pair: pair[1]["passed"]):
                if suite is not None and value["suite"] != suite:
                    continue
                result = local_path(value["result"]) if value.get("result") else None
                log = local_path(value["log"]) if value.get("log") else None
                sources[name] = ResultSource(result, log, value.get("error", ""))
            if job.exit_code and (not sources or job.error and suite is None):
                sources["Run setup or cleanup"] = ResultSource(error=job.error, console="".join(job.log))
            self.show_result_window(sources)
        self.guarded(action)

    def open_result_report(self):
        path = filedialog.askopenfilename(parent=self.root, title="Open a Studio result.json or batch-result.json",
                                         initialdir=self.library.workspace, filetypes=[("Studio report JSON", "*.json")])
        if path:
            self.guarded(lambda: self.show_result_window(open_saved_report(Path(path))))

    def show_result_window(self, sources):
        if not sources:
            self.status.set("There are no completed test steps for this run.")
            return
        window = tk.Toplevel(self.root)
        window.title("Studio test results")
        window.geometry("950x560")
        window.minsize(650, 360)
        body = ttk.Frame(window, padding=12)
        body.pack(fill="both", expand=True)
        test = tk.StringVar(master=window, value=next(iter(sources)))
        picker = ttk.Combobox(body, textvariable=test, values=tuple(sources), state="readonly")
        picker.pack(fill="x", pady=(0, 8))
        panes = ttk.Panedwindow(body, orient="horizontal")
        panes.pack(fill="both", expand=True)
        steps = ttk.Treeview(panes, columns=("status",), selectmode="browse", show=("tree", "headings"))
        steps.heading("#0", text="Step")
        steps.heading("status", text="Result")
        steps.column("#0", width=240)
        steps.column("status", width=78, stretch=False)
        panes.add(steps)
        details = ttk.Frame(panes)
        panes.add(details, weight=1)
        output = tk.Text(details, wrap="word", font=("Consolas", 10), state="disabled", width=55)
        scroll = ttk.Scrollbar(details, orient="vertical", command=output.yview)
        output.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        output.pack(fill="both", expand=True)
        rows = []

        def show_step(_event=None):
            selection = steps.selection()
            if not selection:
                return
            row = rows[int(selection[0])]
            parts = [f"{row.status} · {row.name}", row.action, row.reason]
            if row.log:
                parts.append(f"Log file\n{row.log}")
            parts.append(row.console or log_tail(row.log) or "No log was saved for this step.")
            output.configure(state="normal")
            output.delete("1.0", "end")
            output.insert("1.0", "\n\n".join(part for part in parts if part))
            output.configure(state="disabled")

        def select_test(_event=None):
            try:
                rows[:] = result_steps(sources[test.get()])
            except (OSError, ValueError, TypeError, KeyError) as exc:
                rows[:] = [ResultStep("Read saved report", "Failed", str(exc))]
            steps.delete(*steps.get_children())
            for index, row in enumerate(rows):
                steps.insert("", "end", iid=str(index), text=row.name, values=(row.status,),
                             image=self.result_icons.get(row.status, ""))
            first = str(next((i for i, row in enumerate(rows) if row.status == "Failed"), 0))
            if rows:
                steps.selection_set(first)
                steps.see(first)
                show_step()

        steps.bind("<<TreeviewSelect>>", show_step)
        picker.bind("<<ComboboxSelected>>", select_test)
        select_test()

    def update_progress(self):
        job = self.jobs.get(self.current_job.get())
        if job is None:
            return
        if job.started is None:
            text = "Queued"
        else:
            elapsed = (job.finished if job.finished is not None else time.monotonic()) - job.started
            minutes, seconds = divmod(int(elapsed), 60)
            state = "Running" if job.exit_code is None else ("Finished" if job.exit_code == 0 else "Ended with errors")
            text = f"{state} · {minutes}:{seconds:02d} elapsed"
        if job.total:
            text += f" · {job.completed} of {job.total} {job.unit} complete"
        self.progress_text.set(text)
        if job.started is not None and job.exit_code is None and not job.completed:
            if str(self.progress_bar.cget("mode")) != "indeterminate":
                self.progress_bar.configure(mode="indeterminate", maximum=100, value=0)
                self.progress_bar.start(60)
        else:
            self.progress_bar.stop()
            self.progress_bar.configure(mode="determinate", maximum=job.total or 1,
                                        value=job.completed if job.total else int(job.exit_code == 0))

    def mark_test(self, job, suite, state):
        job.states[suite] = state
        self.suite_status.setdefault(job.scope, {})[suite] = state

    def update_result_icons(self, *, running_only=False):
        frames = self.result_icons["Running"]
        frame = frames[int(time.monotonic() * 8) % len(frames)]
        statuses = self.suite_status.get(self.removal_scope(), {})
        for item, row in self.library_rows.items():
            state = statuses.get(row["id"], "")
            if not running_only or state == "Running":
                icon = frame if state == "Running" else self.result_icons.get(state, "")
                self.tree.item(item, image=icon, text=state)
        job = self.jobs.get(self.current_job.get())
        icon = ""
        if job and job.started is not None:
            icon = frame if job.exit_code is None else self.result_icons["Passed" if job.exit_code == 0 else "Failed"]
        self.status_icon.configure(image=icon)

    def finish_job(self, job, exit_code):
        job.finished = time.monotonic()
        job.exit_code = exit_code
        job.message = job.final_message or ("Operation completed" if exit_code == 0 else
                                            "Operation failed — see Results")
        for suite, state in list(job.states.items()):
            if state == "Running":
                self.mark_test(job, suite, "Failed" if exit_code else "Not run")
            elif state == "Queued":
                self.mark_test(job, suite, "Not run")

    def handle_event(self, job, item):
        try:
            value = json.loads(item)
        except ValueError:
            return item
        if not isinstance(value, dict):
            return item
        event = value.get("event")
        if event == "test_servers":
            job.final_message = self.show_servers(value)
            item = job.final_message + "\n"
        elif event == "error":
            job.error = job.final_message = value["error"].removeprefix("ValueError: ")
            item = job.final_message + "\n"
        elif event == "test_server":
            state = value["state"]
            messages = {"Stopped": "Docker test server is stopped.", "Preparing": "Preparing the Docker test server.",
                        "Loading": "Waiting for the game worlds to load.", "Ready": "Docker test server is ready.",
                        "Finishing shutdown": "Finishing the previous test-server shutdown before starting it.",
                        "Running": "Using the running Docker test server."}
            job.message = messages.get(state, state)
            item = job.message + "\n"
        elif event == "run_preparing":
            job.total = value["cases"]
            job.message = "Verifying the test build before running the cases."
            item = job.message + "\n"
        elif event == "batch_started":
            job.total, job.unit = value["runs"], "tests"
        elif event in ("batch_job_started", "batch_job_finished", "case_started", "case_finished"):
            batch = event.startswith("batch")
            name = value["suite" if batch else "id"]
            label = name.replace("_", " ")
            if event.endswith("started"):
                state = "Running"
                job.message = "Running " + label + "…"
            else:
                state = "Passed" if value["passed"] else "Failed"
                job.completed += 1
                duration = "" if batch else f" ({value.get('seconds', 0):.1f} seconds)"
                job.message = f"{label.capitalize()} {state.lower()}{duration}."
            if batch:
                self.mark_test(job, name, state)
                if event == "batch_job_finished":
                    job.results[value.get("id", name)] = value
            item = job.message + "\n"
            if state == "Failed" and value.get("error"):
                item += (value["action"] + "\n" if value.get("action") else "") + value["error"] + "\n"
        elif event in ("run_finished", "batch_finished"):
            if event == "run_finished":
                job.final_message = "Test passed." if value["passed"] else "Test failed. Review the case logs."
                suite = next(iter(job.states))
                self.mark_test(job, suite, "Passed" if value["passed"] else "Failed")
                job.results[suite] = dict(value, suite=suite, result=value["evidence"].rstrip("/") + "/result.json")
            else:
                job.final_message = ("All selected tests passed." if value["passed"] else
                                     "The run ended with failures. Review the test reports.")
            item = job.final_message + "\nReports saved in " + str(local_path(value["evidence"])) + "\n"
        if value.get("state") == "armed_waiting_for_server_events":
            self.capture_ranges.set("")
        if "id" in value and len(str(value["id"])) == 32:
            self.recording.set(value["id"])
        if "events" in value or value.get("state") == "armed_waiting_for_server_events":
            self.timeline.configure(state="normal")
            self.timeline.delete("1.0", "end")
            self.timeline.insert("1.0", json.dumps(value, indent=2))
            self.timeline.configure(state="disabled")
        if value.get("format") == "swg-test-studio":
            self.set_editor(value)
        return item

    def poll(self):
        selected = self.current_job.get()
        viewed = self.jobs.get(selected)
        previous_message = viewed.message if viewed else None
        changed = selected_event = finished = False
        while not self.messages.empty():
            label, item = self.messages.get()
            job = self.jobs[label]
            changed = True
            selected_event |= label == selected
            if isinstance(item, int):
                finished = True
                self.finish_job(job, item)
            else:
                job.log.append(self.handle_event(job, item))
        if finished:
            self.start_jobs()
        if selected_event or (viewed and viewed.message != previous_message):
            self.show_job()
        else:
            self.update_progress()
            self.update_result_icons(running_only=not changed)
        self.root.after(100, self.poll)

    def close(self):
        if any(job.exit_code is None for job in self.jobs.values()):
            messagebox.showinfo("Operations running", "Wait for the active and queued operations before closing Studio.", parent=self.root)
            return
        if self.recording.get() and not messagebox.askyesno("Close Studio?", "Stop any active recording before closing. Controls also expire automatically. Close now?", parent=self.root):
            return
        self.root.destroy()


def launch(workspace, collection=None):
    root = tk.Tk()
    Studio(root, workspace, collection)
    root.mainloop()
