"""Native local UI. No HTTP listener, browser commands or game-client patches."""
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .model import loads, validate
from .store import Library, write_json


class Studio:
    def __init__(self, root, workspace):
        self.root, self.library = root, Library(workspace)
        self.messages, self.process = queue.Queue(), None
        self.environment = tk.StringVar()
        self.recording = tk.StringVar()
        self.capture_ranges = tk.StringVar()
        self.role = tk.StringVar(value="actor")
        self.status = tk.StringVar(value="Select an example or create a test. Live operations require a prepared fixture.")
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
        ttk.Entry(bar, textvariable=self.environment).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(bar, text="Open…", command=self.choose_environment).pack(side="left")
        ttk.Button(bar, text="New environment…", command=self.new_environment).pack(side="left", padx=5)
        self.tabs = ttk.Notebook(shell)
        self.tabs.pack(fill="both", expand=True)
        library = ttk.Frame(self.tabs, padding=10)
        editor = ttk.Frame(self.tabs, padding=10)
        recording = ttk.Frame(self.tabs, padding=10)
        results = ttk.Frame(self.tabs, padding=10)
        for frame, name in ((library, "Library"), (editor, "Edit"), (recording, "Record"), (results, "Run & Results")):
            self.tabs.add(frame, text=name)
        self.tree = ttk.Treeview(library, columns=("title", "kind", "roles"), show="headings")
        for name, text, width in (("title", "Test", 650), ("kind", "Source", 90), ("roles", "Roles", 170)):
            self.tree.heading(name, text=text)
            self.tree.column(name, width=width)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _: self.open_selected())
        actions = ttk.Frame(library)
        actions.pack(fill="x", pady=8)
        for text, callback in (("Open", self.open_selected), ("Refresh", self.refresh), ("Import JSON…", self.import_suite)):
            ttk.Button(actions, text=text, command=callback).pack(side="left", padx=(0, 6))
        ttk.Label(editor, text="Edit the typed JSON below. Give example copies a new ID. Each session includes logout and full save checks.").pack(anchor="w")
        self.editor = tk.Text(editor, wrap="none", undo=True, font=("Consolas", 11))
        self.editor.pack(fill="both", expand=True, pady=8)
        row = ttk.Frame(editor)
        row.pack(fill="x")
        for text, callback in (("Validate", self.validate), ("Approve reviewed expectations", self.approve), ("Save", self.save), ("Preview run", self.preview), ("Run", self.run)):
            ttk.Button(row, text=text, command=callback).pack(side="left", padx=(0, 6))
        ttk.Label(recording, wraplength=950, text="Record uses opt-in server hooks and a dedicated character in the unchanged Windows client. Start beside Tansaari's or Gamma's shuttle and stay still. Completed terminal interactions become a test draft. Review its expected outcomes, stop recording and log the character out before Run. Unsupported actions remain blocked.").pack(anchor="w", pady=(0, 12))
        row = ttk.Frame(recording)
        row.pack(fill="x")
        ttk.Label(row, text="Role").pack(side="left")
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
        self.output = tk.Text(results, wrap="word", font=("Consolas", 10), state="disabled")
        self.output.pack(fill="both", expand=True, pady=8)
        ttk.Label(shell, textvariable=self.status, wraplength=1060).pack(anchor="w", pady=(10, 0))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()
        root.after(100, self.poll)

    def guarded(self, callback):
        try:
            return callback()
        except Exception as exc:
            self.status.set(str(exc))
            messagebox.showerror("SWG Test Studio", str(exc), parent=self.root)

    def refresh(self):
        def action():
            self.tree.delete(*self.tree.get_children())
            for row in self.library.list():
                self.tree.insert("", "end", iid=row["origin"] + ":" + row["id"], values=(row["title"], row["origin"], ", ".join(row["roles"])))
        self.guarded(action)

    def set_editor(self, value):
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", json.dumps(value, indent=2, ensure_ascii=False))
        self.tabs.select(1)

    def open_selected(self):
        if self.tree.selection():
            self.guarded(lambda: self.set_editor(self.library.get(self.tree.selection()[0].split(":", 1)[1])))

    def current(self):
        return validate(loads(self.editor.get("1.0", "end")))

    def validate(self):
        def action():
            validate(self.current(), runnable=True)
            self.status.set("Valid supported suite. Preview checks environment bindings before Run.")
        self.guarded(action)

    def approve(self):
        def action():
            suite = self.current()
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
            path = self.library.workspace / "suites" / (suite["id"] + ".json")
            replace = path.exists()
            if replace and not messagebox.askyesno("Replace saved test?", "Replace " + suite["id"] + "?", parent=self.root):
                return
            self.library.save(suite, replace=replace)
            self.refresh()
            self.status.set("Saved " + suite["id"])
        self.guarded(action)

    def import_suite(self):
        path = filedialog.askopenfilename(filetypes=[("Test JSON", "*.json")])
        if path:
            self.guarded(lambda: self.set_editor(loads(Path(path).read_text(encoding="utf-8"))))

    def choose_environment(self):
        path = filedialog.askopenfilename(filetypes=[("Environment JSON", "*.json")])
        if path:
            self.environment.set(path)

    def new_environment(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="environment.json")
        if not path:
            return
        def action():
            write_json(path, {"schema_version": 1, "name": "My isolated SWG fixture", "server_checkout": "/path/to/swg-checkout",
                             "folder": "/tmp/swg-cold-test-0123abcd/client-012345abcdef", "binary": "/path/to/matched-elf64-driver", "bindings": {"actor": "beta"}})
            self.environment.set(path)
            self.status.set("Edit the environment JSON with your Linux checkout, fixture and matched driver paths.")
        self.guarded(action)

    def env(self):
        return self.environment.get()

    def preview(self):
        self.guarded(lambda: self.submit_suite("plan"))

    def run(self):
        self.guarded(lambda: self.submit_suite("run"))

    def submit_suite(self, command):
        suite = self.current()
        validate(suite, runnable=True)
        if not self.env():
            raise ValueError("Select an environment JSON first")
        try:
            existing = self.library.get(suite["id"])
        except ValueError:
            existing = None
        if existing != suite:
            raise ValueError("Save your test before previewing or running it")
        self.tabs.select(3)
        self.job(command, suite["id"], "--environment", self.env())

    def start_recording(self):
        arguments = ["record-start", "--environment", self.env()]
        for role in self.role.get().split(","):
            arguments.extend(("--role", role.strip()))
        self.job(*arguments)

    def export_draft(self):
        clips = [value.strip() for value in self.capture_ranges.get().split(",") if value.strip()]
        extra = [item for value in clips for item in ("--range", value)]
        self.job("record-draft", "--recording", self.recording.get(), "--id", "recorded_test",
                 "--title", "Recorded gameplay - review required", *extra)

    def job(self, *args):
        if self.process is not None:
            self.status.set("An operation is already running")
            return
        launcher = Path(__file__).with_name("entry.py")
        argv = [sys.executable, str(launcher), "--workspace", str(self.library.workspace), *args]
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


def launch(workspace):
    root = tk.Tk()
    Studio(root, workspace)
    root.mainloop()
