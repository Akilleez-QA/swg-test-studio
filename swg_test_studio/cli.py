"""CLI for the same suite, environment and recording services used by the GUI."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from .backend import environment, plan, run_suite
from .model import loads, validate
from .store import DEFAULT_WORKSPACE, Library, read_json


def emit(value):
    # ASCII JSON is portable across Windows console encodings and UTF-8 GUI pipes.
    print(json.dumps(value, ensure_ascii=True, allow_nan=False), flush=True)


def windows_relay(args, workspace):
    """Array-only WSL dispatch; the UI never supplies shell text or a plan."""
    distro = os.environ.get("SWG_WSL_DISTRO", "Ubuntu-24.04")
    def linux(path):
        value = str(path)
        if value.startswith("/"):
            return value
        return subprocess.check_output(["wsl.exe", "-d", distro, "--exec", "wslpath", "-a", str(Path(value).absolute())], text=True).strip()
    launcher = Path(__file__).with_name("entry.py")
    forwarded = list(args)
    if "--workspace" not in forwarded:
        forwarded[0:0] = ["--workspace", linux(workspace)]
    for option in ("--workspace", "--environment"):
        if option in forwarded:
            index = forwarded.index(option) + 1
            forwarded[index] = linux(forwarded[index])
    return subprocess.call(["wsl.exe", "-d", distro, "--exec", "python3", linux(launcher), *forwarded])


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="SWG Test Studio — desktop, saved driver suites and fixture recording")
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("gui", help="Open the local graphical application")
    commands.add_parser("list", help="List bundled examples and your saved tests")
    for action in ("show", "validate"):
        child = commands.add_parser(action)
        child.add_argument("suite")
    child = commands.add_parser("save", help="Validate and save a user-defined JSON suite")
    child.add_argument("--file", type=Path, required=True)
    child.add_argument("--replace", action="store_true")
    for action in ("plan", "run"):
        child = commands.add_parser(action)
        child.add_argument("suite")
        child.add_argument("--environment", type=Path, required=True)
    commands.add_parser("environment-template", help="Print an editable environment example (contains no credentials)")
    child = commands.add_parser("record-start")
    child.add_argument("--environment", type=Path, required=True)
    child.add_argument("--role", required=True)
    child.add_argument("--seconds", type=int, default=600)
    for action in ("record-status", "record-stop", "record-draft"):
        child = commands.add_parser(action)
        child.add_argument("--recording", required=True)
        if action == "record-draft":
            child.add_argument("--id", required=True)
            child.add_argument("--title", required=True)
            child.add_argument("--range", dest="capture_ranges", action="append", help="Explicit FIRST:LAST clip; repeat for separate cases")
    args = parser.parse_args(argv)
    if args.command is None or args.command == "gui":
        from .gui import launch
        launch(args.workspace)
        return 0
    if os.name == "nt" and (args.command == "run" or args.command.startswith("record-")):
        return windows_relay(argv, args.workspace)
    library = Library(args.workspace)
    try:
        if args.command == "list":
            emit({"suites": library.list()})
        elif args.command == "show":
            emit(library.get(args.suite))
        elif args.command == "validate":
            validate(library.get(args.suite), runnable=True)
            emit({"valid": True, "suite": args.suite})
        elif args.command == "save":
            emit({"saved": str(library.save(read_json(args.file), replace=args.replace))})
        elif args.command == "environment-template":
            emit({"schema_version": 1, "name": "My isolated SWG fixture",
                  "server_checkout": "/path/to/swg-checkout", "folder": "/tmp/swg-cold-test-0123abcd/client-012345abcdef",
                  "binary": "/path/to/matched-elf64-driver", "bindings": {"actor": "beta"}})
        elif args.command in ("plan", "run"):
            suite, env = library.get(args.suite), environment(args.environment)
            if args.command == "plan":
                emit(plan(suite, env))
            else:
                result = run_suite(suite, env, args.workspace, emit)
                emit(result)
                return 0 if result["passed"] else 1
        else:
            from . import recording
            if args.command == "record-start":
                result = recording.start(environment(args.environment), args.workspace, args.role, args.seconds)
            elif args.command == "record-status":
                result = recording.status(args.workspace, args.recording)
            elif args.command == "record-stop":
                result = recording.stop(args.workspace, args.recording)
            else:
                from .clips import parse_ranges
                result = recording.draft(args.workspace, args.recording, args.id, args.title, parse_ranges(args.capture_ranges))
            emit(result)
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        emit({"event": "error", "error": type(exc).__name__ + ": " + str(exc)})
        return 130 if isinstance(exc, KeyboardInterrupt) else 1


if __name__ == "__main__":
    raise SystemExit(main())
