"""The desktop form for Studio's existing environment format."""

import json
import os
from pathlib import Path, PureWindowsPath
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .backend import environment_template, validate_environment
from .store import write_json


def linux_path(value):
    value = value.strip()
    path = PureWindowsPath(value)
    drive = path.drive.lower()
    if path.is_absolute() and len(drive) == 2 and drive[1] == ":":
        return "/mnt/" + drive[0] + "/" + "/".join(path.parts[1:])
    if drive.startswith(("\\\\wsl.localhost\\", "\\\\wsl$\\")):
        distro = os.environ.get("SWG_WSL_DISTRO", "Ubuntu-24.04")
        if drive.rsplit("\\", 1)[1] != distro.lower():
            raise ValueError(f"Choose a path in the configured WSL distribution ({distro})")
        return "/" + "/".join(path.parts[1:])
    return value


FIELDS = (
    ("name", "Profile name", "A label to help you recognize this setup."),
    ("server_checkout", "Server checkout", "The SWG server source folder containing devtools/zones."),
    ("folder", "Test fixture folder", "The prepared client-* folder inside /tmp/swg-cold-test-* in WSL."),
    ("binary", "64-bit driver", "The ELF64 driver executable produced by the server's build_protocol_driver64.py."),
)


class EnvironmentDialog(tk.Toplevel):
    def __init__(self, parent, workspace, on_saved, *, path=None, data=None, roles=()):
        super().__init__(parent)
        self.workspace, self.on_saved, self.path = Path(workspace), on_saved, path
        self.title("Environment setup")
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        initial = data or {"name": "My isolated SWG fixture", "bindings": {}}
        self.values = {key: tk.StringVar(self, value=initial.get(key, "")) for key, _, _ in FIELDS}

        content = ttk.Frame(self, padding=16)
        content.grid(sticky="nsew")
        content.columnconfigure(1, weight=1)
        ttk.Label(content, wraplength=610, text=(
            "An environment is a reusable setup profile. It tells Studio which server source, "
            "isolated fixture and driver to use, and which dedicated characters play the test roles. "
            "Studio saves these selections as JSON. Use the form to create or edit it."
        )).grid(row=0, columnspan=3, sticky="w", pady=(0, 12))
        for index, (key, label, help_text) in enumerate(FIELDS, 1):
            row = index * 2
            ttk.Label(content, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10))
            ttk.Entry(content, textvariable=self.values[key], width=57).grid(row=row, column=1, sticky="ew")
            if key != "name":
                ttk.Button(content, text="Browse…", command=lambda field=key: self.browse(field)).grid(
                    row=row, column=2, padx=(6, 0))
            ttk.Label(content, text=help_text, wraplength=460).grid(
                row=row + 1, column=1, columnspan=2, sticky="w", pady=(2, 8))

        bindings = ttk.LabelFrame(content, text="Test roles", padding=8)
        bindings.grid(row=10, columnspan=3, sticky="ew", pady=(4, 8))
        ttk.Label(bindings, wraplength=590, text=(
            "Use the roles shown beside the selected test. For example, bind actor to tester "
            "if tester.json is that character's registry in the fixture's protocol-driver folder. "
            "Enter registry keys without .json. Leave unused rows empty."
        )).grid(row=0, columnspan=2, sticky="w", pady=(0, 5))
        ttk.Label(bindings, text="Role in the test").grid(row=1, column=0, sticky="w")
        ttk.Label(bindings, text="Dedicated registry key").grid(row=1, column=1, sticky="w")
        existing = initial["bindings"]
        names = list(dict.fromkeys((*existing, *roles)))[:5]
        self.bindings = []
        for index in range(5):
            role = names[index] if index < len(names) else ""
            pair = (tk.StringVar(self, value=role), tk.StringVar(self, value=existing.get(role, "")))
            self.bindings.append(pair)
            for column, variable in enumerate(pair):
                ttk.Entry(bindings, textvariable=variable, width=27).grid(
                    row=index + 2, column=column, sticky="w", padx=(0, 8), pady=2)

        ttk.Label(content, wraplength=610, text=(
            "Paste Linux/WSL paths or use Browse. Windows drive paths use the default /mnt/ mapping. "
            "Save checks the profile format. "
            "Preview checks the test's role bindings. Run checks the live fixture and driver."
        )).grid(row=11, columnspan=3, sticky="w", pady=(0, 8))
        buttons = ttk.Frame(content)
        buttons.grid(row=12, columnspan=3, sticky="ew")
        ttk.Button(buttons, text="Show example values", command=self.show_example).pack(side="left")
        ttk.Button(buttons, text="Save & use…", command=self.save).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=6)
        self.resizable(True, False)

    def browse(self, key):
        choose = filedialog.askopenfilename if key == "binary" else filedialog.askdirectory
        path = choose(parent=self, title=dict((name, label) for name, label, _ in FIELDS)[key])
        if path:
            self.values[key].set(path)

    def show_example(self):
        messagebox.showinfo(
            "Example environment",
            "These values illustrate the format. Use the paths and registry keys from your own setup.\n\n"
            + json.dumps(environment_template(), indent=2),
            parent=self,
        )

    def profile(self):
        bindings = {}
        for role, registry in self.bindings:
            name, key = role.get().strip(), registry.get().strip()
            if not name and not key:
                continue
            if not name or not key:
                raise ValueError("Fill in both columns for each test role, or clear the unused row.")
            if name in bindings:
                raise ValueError(f"Use each test role once ({name}).")
            bindings[name] = key
        return validate_environment({
            "schema_version": 1, "name": self.values["name"].get().strip(),
            **{key: linux_path(self.values[key].get()) for key, _, _ in FIELDS if key != "name"},
            "bindings": bindings,
        })

    def save(self):
        try:
            data = self.profile()
            self.workspace.mkdir(parents=True, exist_ok=True)
            default = self.path or self.workspace / "environment.json"
            path = filedialog.asksaveasfilename(
                parent=self, initialdir=default.parent, initialfile=default.name,
                defaultextension=".json", filetypes=[("Environment JSON", "*.json")], confirmoverwrite=True,
            )
            if not path:
                return
            path = Path(path)
            write_json(path, data, replace=path.exists())
            self.on_saved(path, data)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Check the environment", str(exc), parent=self)
            return
        self.destroy()
