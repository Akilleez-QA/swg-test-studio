"""Native local UI. No HTTP listener, browser commands or game-client patches."""
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from .backend import environment
from .batch import MAX_JOBS, batch_template
from .collection import FORMAT as COLLECTION_FORMAT, MAX_BYTES, Collection, is_driver_suite, validate_entry
from .environment_ui import EnvironmentDialog
from .model import loads, validate
from .store import Library, read_json, write_json


EXAMPLE_DETAILS = {
    "login_relogin": "A good first test. Log in, log out, then log in again to verify the character saved. Use an existing dedicated character.",
    "create_character": "Create a dedicated character and verify the first login, logout and save. Choose a registry key reserved for character creation.",
    "driver_guards": "Run the server checkout's driver unit checks. The suite has no character roles and needs no running game services.",
    "gamma_shuttle": "Use the original shuttle terminal to travel from Tansaari to Gamma and back. Start at Tansaari with an actor prepared for shuttle travel.",
    "terminal_journey": "Replay both shuttle directions in one session. The fixture positions a solo Tansaari actor near the terminals.",
    "shuttle_recorded_cases": "Replay three reviewed clips covering cancellation and both travel directions. Use a solo actor in either supported station.",
    "ord_round_trip": "Replay a recorded launch from Tansaari to Ord Mantell and land in the authored hangar. Use a solo Tansaari pilot.",
    "ord_group_sequence": "Form a group, change leaders, launch, land and disband. Bind two distinct dedicated actors who start solo at Tansaari.",
    "ship_and_group": "Run the existing driver scenario for owned ships, landing and group routing. Bind two dedicated Tansaari actors.",
    "group_disband": "Verify that former members travel independently and can join a new group. Use three actors in the reviewed Rryatt/Ord fixture.",
}

GETTING_STARTED = (
    "1. Open the selected login and relogin example in the Library. Click Validate to inspect it offline.\n\n"
    "2. Use Copy example to make an editable test. The Library shows each example's roles and prerequisites.\n\n"
    "3. Choose Set up environment to connect the test to your isolated fixture and dedicated characters. "
    "Use the prepared fixture folder and matched driver executable from the SWG server setup. "
    "The server checkout's docs/protocol-driver64.md explains how to prepare both.\n\n"
    "4. Preview run shows the planned actions and setup. Start the matching test fixture before Run or Record.\n\n"
    "5. In Record, enter the environment's role names, separated by commas when recording two characters. "
    "Stop and export a draft, review its expectations, then save it for replay."
)


class Studio:
    def __init__(self, root, workspace, collection=None):
        self.root, self.library = root, Library(workspace)
        self.messages, self.process = queue.Queue(), None
        self.library_rows = {}
        self.collection = None
        self.library_title = tk.StringVar(value="Examples and saved tests")
        self.filter_text = tk.StringVar()
        self.environment = tk.StringVar()
        self.environment_name = tk.StringVar(value="Set up an environment when you are ready to preview, run or record.")
        self.example_details = tk.StringVar()
        self.recording = tk.StringVar()
        self.capture_ranges = tk.StringVar()
        self.role = tk.StringVar(value="actor")
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
        ttk.Label(shell, text="Record gameplay. Define expectations. Replay with the existing 64-bit driver.").pack(anchor="w", pady=(3, 14))
        bar = ttk.Frame(shell)
        bar.pack(fill="x", pady=(0, 12))
        ttk.Label(bar, text="Environment").pack(side="left")
        ttk.Entry(bar, textvariable=self.environment, state="readonly").pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(bar, text="Open profile…", command=self.choose_environment).pack(side="left")
        ttk.Button(bar, text="Set up environment…", command=self.configure_environment).pack(side="left", padx=5)
        ttk.Button(bar, text="Help", command=self.help).pack(side="left")
        ttk.Label(shell, textvariable=self.environment_name, wraplength=760).pack(anchor="w", pady=(0, 8))
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
        self.tree = ttk.Treeview(listing, columns=("title", "kind", "roles"), show="headings")
        for name, text, width in (("title", "Test", 650), ("kind", "Source", 90), ("roles", "Roles", 170)):
            self.tree.heading(name, text=text)
            self.tree.column(name, width=width)
        scrollbar = ttk.Scrollbar(listing, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _: self.open_selected())
        self.tree.bind("<<TreeviewSelect>>", self.show_details)
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
        ttk.Label(editor, text="Edit the typed JSON below. Give example copies a new ID. Each session includes logout and full save checks.").pack(anchor="w")
        self.editor = tk.Text(editor, wrap="none", undo=True, font=("Consolas", 11))
        self.editor.pack(fill="both", expand=True, pady=8)
        row = ttk.Frame(editor)
        row.pack(fill="x")
        for text, callback in (("Validate", self.validate), ("Approve reviewed expectations", self.approve), ("Save", self.save), ("Export test…", self.export_test), ("Preview run", self.preview), ("Run", self.run)):
            ttk.Button(row, text=text, command=callback).pack(side="left", padx=(0, 6))
        ttk.Label(recording, wraplength=760, text=(
            "Set up an environment with a recording-enabled fixture, then enter the bound role names below. "
            "Record supported shuttle trips, Ord launch and landing, or two-character group actions. "
            "Stop, export a draft, and review its expectations. Log out and allow the character to unload before replay."
        )).pack(anchor="w", pady=(0, 12))
        row = ttk.Frame(recording)
        row.pack(fill="x")
        ttk.Label(row, text="Role names").pack(side="left")
        ttk.Entry(row, textvariable=self.role, width=18).pack(side="left", padx=6)
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
                             ("Run batch…", lambda: self.submit_batch("run-batch"))):
            ttk.Button(batch_actions, text=text, command=action).pack(side="left", padx=(0, 6))
        ttk.Label(results, wraplength=900, text=(
            "Batch jobs use the selected collection or workspace library. Each job names its own environment profile. "
            "Suites sharing a server checkout or test fixture run in order."
        )).pack(anchor="w", pady=(6, 0))
        self.output = tk.Text(results, wrap="word", font=("Consolas", 10), state="disabled")
        self.output.pack(fill="both", expand=True, pady=8)
        ttk.Label(shell, textvariable=self.status, wraplength=1060).pack(anchor="w", pady=(10, 0))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()
        if collection:
            self.guarded(lambda: self.open_collection(collection))
        default = self.library.workspace / "environment.json"
        if default.is_file():
            try:
                self.use_environment(default, environment(default))
            except (ValueError, OSError) as exc:
                self.status.set(f"Open or set up an environment. The saved profile could not load ({exc}).")
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
            self.tree.delete(*self.tree.get_children())
            self.library_rows = {}
            for row in rows:
                if needle and needle not in (row["id"] + " " + row["title"]).casefold():
                    continue
                item = row["origin"] + ":" + row["id"]
                self.library_rows[item] = row
                origin = {"example": "Example", "user": "My test", "studio": "Studio", "driver": "Driver"}[row["origin"]]
                self.tree.insert("", "end", iid=item, values=(row["title"], origin, ", ".join(row["roles"]) or "None"))
            starter = "studio:login_relogin" if self.collection else "example:login_relogin"
            item = selected[0] if selected and self.tree.exists(selected[0]) else starter
            if not self.tree.exists(item) and self.library_rows:
                item = next(iter(self.library_rows))
            if self.tree.exists(item):
                self.tree.selection_set(item)
                self.tree.see(item)
            self.show_details()
            state = "normal" if self.collection else "disabled"
            self.save_collection_button.configure(state=state)
            self.close_collection_button.configure(state=state)
            if invalid:
                names = ", ".join(invalid[:3]) + (" and others" if len(invalid) > 3 else "")
                self.status.set("Skipped invalid saved test files: " + names)
        self.guarded(action)

    def selected_row(self):
        selection = self.tree.selection()
        return self.library_rows[selection[0]] if selection else None

    def show_details(self, _event=None):
        row = self.selected_row()
        example = row and row["origin"] == "example"
        self.copy_button.configure(state="normal" if example else "disabled")
        if row:
            if row["origin"] == "driver":
                notes = "Open to inspect, edit, or export this driver manifest. Use the original server harness and its required fixture to run an authorized case."
            else:
                notes = EXAMPLE_DETAILS.get(row["id"], "Open this test to inspect its steps and expected results.")
            roles = ", ".join(row["roles"]) or "None"
            self.example_details.set(f"{notes}\nRoles for this test: {roles}")
        else:
            self.example_details.set("Select a test to see what it checks and which roles it needs.")

    def copy_example(self):
        def action():
            row = self.selected_row()
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

    def set_editor(self, value):
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", json.dumps(value, indent=2, ensure_ascii=False))
        self.tabs.select(1)

    def open_selected(self):
        row = self.selected_row()
        if row:
            self.guarded(lambda: self.set_editor(self.collection.get(row["id"]) if self.collection else
                                                 validate(read_json(row["path"]))))

    def current(self):
        return validate_entry(loads(self.editor.get("1.0", "end")))

    def studio_suite(self):
        suite = self.current()
        if is_driver_suite(suite):
            raise ValueError("Driver manifests use the original server harness. Select a Studio test for replay.")
        return suite

    def validate(self):
        def action():
            suite = self.current()
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

    def export_test(self):
        def action():
            suite = self.current()
            path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".json",
                                                initialfile=suite["id"] + ".json", filetypes=[("Test JSON", "*.json")])
            if path:
                if self.collection and Path(path).resolve() == self.collection.path.resolve():
                    raise ValueError("Choose a different filename for the individual test")
                write_json(path, suite, replace=Path(path).exists())
                self.status.set("Exported " + path)
        self.guarded(action)

    def choose_environment(self):
        path = filedialog.askopenfilename(parent=self.root, filetypes=[("Environment JSON", "*.json")])
        if path:
            self.guarded(lambda: self.use_environment(Path(path), environment(path)))

    def use_environment(self, path, data):
        self.environment.set(str(path))
        self.environment_name.set("Selected profile: " + data["name"])
        self.status.set("Environment selected. Preview a test to check its role bindings.")

    def configure_environment(self):
        def action():
            row = self.selected_row()
            roles = row["roles"] if row else ()
            if self.tabs.index(self.tabs.select()) == 1 and self.editor.get("1.0", "end").strip():
                try:
                    roles = self.current()["roles"]
                except ValueError:
                    pass
            path = Path(self.env()) if self.env() else None
            return EnvironmentDialog(self.root, self.library.workspace, self.use_environment, path=path,
                                     data=environment(path) if path else None, roles=roles)
        return self.guarded(action)

    def env(self):
        return self.environment.get()

    def preview(self):
        self.guarded(lambda: self.submit_suite("plan"))

    def run(self):
        self.guarded(lambda: self.submit_suite("run"))

    def submit_suite(self, command):
        suite = self.studio_suite()
        validate(suite, runnable=True)
        if not self.env():
            raise ValueError("Choose Set up environment to create a profile, or Open profile to use an existing one.")
        try:
            existing = (self.collection or self.library).get(suite["id"])
        except ValueError:
            existing = None
        if existing != suite:
            raise ValueError("Save your test before previewing or running it")
        self.tabs.select(3)
        self.job(command, suite["id"], "--environment", self.env())

    def start_recording(self):
        def action():
            if not self.env():
                raise ValueError("Choose Set up environment before recording.")
            arguments = ["record-start", "--environment", self.env()]
            for role in self.role.get().split(","):
                arguments.extend(("--role", role.strip()))
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

    def job(self, *args):
        if self.process is not None:
            self.status.set("An operation is already running")
            return
        launcher = Path(__file__).with_name("entry.py")
        argv = [sys.executable, str(launcher), "--workspace", str(self.library.workspace), *args]
        if self.collection and args[0] in ("plan", "run", "plan-batch", "run-batch"):
            argv[4:4] = ["--collection", str(self.collection.path)]
        try:
            self.process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        except Exception as exc:
            self.status.set(str(exc))
            return
        process = self.process
        def read():
            for line in process.stdout:
                self.messages.put(line)
            self.messages.put({"finished": process.wait()})
        threading.Thread(target=read, daemon=True).start()
        self.status.set("Running " + args[0] + "…")

    def poll(self):
        while not self.messages.empty():
            item = self.messages.get()
            if isinstance(item, dict):
                self.process = None
                self.status.set("Operation completed" if item["finished"] == 0 else "Operation failed — see Results")
                continue
            self.output.configure(state="normal")
            self.output.insert("end", item)
            self.output.see("end")
            self.output.configure(state="disabled")
            try:
                value = json.loads(item)
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
            except (ValueError, TypeError):
                pass
        self.root.after(100, self.poll)

    def close(self):
        if self.process is not None:
            messagebox.showinfo("Operation running", "Wait for the operation and its cleanup before closing Studio.", parent=self.root)
            return
        if self.recording.get() and not messagebox.askyesno("Close Studio?", "Stop any active recording before closing. Controls also expire automatically. Close now?", parent=self.root):
            return
        self.root.destroy()


def launch(workspace, collection=None):
    root = tk.Tk()
    Studio(root, workspace, collection)
    root.mainloop()
