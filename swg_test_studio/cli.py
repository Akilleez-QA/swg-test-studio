"""CLI for the same suite, environment and recording services used by the GUI."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from .backend import environment, environment_template, plan, run_suite
from .batch import MAX_JOBS, batch_template, prepare_batch, run_batch, run_selected
from .collection import Collection, export_regression, is_driver_suite
from .setup import automatic_environment, creation_roles, register_setup, select_source
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
    if not any(value.split("=", 1)[0] == "--workspace" for value in forwarded):
        forwarded[0:0] = ["--workspace", linux(workspace)]
    for index, argument in enumerate(forwarded):
        option, separator, value = argument.partition("=")
        if option in ("--workspace", "--run-workspace", "--environment", "--collection", "--file", "--source"):
            if separator:
                forwarded[index] = option + "=" + linux(value)
            else:
                forwarded[index + 1] = linux(forwarded[index + 1])
    return subprocess.call(["wsl.exe", "-d", distro, "--exec", "python3", linux(launcher), *forwarded])


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="SWG Test Studio — desktop, saved driver suites and fixture recording")
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--run-workspace", type=Path, help="Separate output folder for an independent run")
    parser.add_argument("--collection", type=Path, help="Use an editable Studio collection JSON")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("gui", help="Open the local graphical application")
    commands.add_parser("list", help="List bundled examples and your saved tests")
    for action in ("show", "validate"):
        child = commands.add_parser(action)
        child.add_argument("suite")
    child = commands.add_parser("save", help="Validate and save a user-defined JSON suite")
    child.add_argument("--file", type=Path, required=True)
    child.add_argument("--replace", action="store_true")
    child = commands.add_parser("export-regression", help="Collect Studio examples and all saved SWG driver suites")
    child.add_argument("--server-checkout", type=Path, required=True)
    child.add_argument("--output", type=Path, required=True)
    for action in ("plan", "run"):
        child = commands.add_parser(action)
        child.add_argument("suite")
        target = child.add_mutually_exclusive_group()
        target.add_argument("--environment", type=Path, help="Explicit CI or test-operator profile")
        target.add_argument("--test-server", help="Choose a verified Docker test server for the saved source folder")
        if action == "run":
            child.add_argument("--keep-running", action="store_true")
            child.add_argument("--source", type=Path, help="Use this source folder instead of the saved selection")
    child = commands.add_parser("install-server-tools", help="Copy the bundled tools into a WhiteNGold server checkout")
    child.add_argument("--source", type=Path, required=True)
    child = commands.add_parser("select-source", help="Choose the SWG source folder")
    child.add_argument("--source", type=Path, required=True)
    child = commands.add_parser("test-servers", help="List verified Docker test servers for the selected source")
    child.add_argument("--start", action="store_true", help="Start a verified server if none are running")
    child = commands.add_parser("register-test-server", help="Connect an already prepared test server to its source")
    child.add_argument("--environment", type=Path, required=True)
    child.add_argument("--replace", action="store_true")
    commands.add_parser("docker-check", help="Build and run Studio's own checks in Docker")
    commands.add_parser("batch-template", help="Print an example batch with two fixture profiles")
    for action in ("plan-batch", "run-batch"):
        child = commands.add_parser(action, help="Preview or run a batch of Studio suites")
        child.add_argument("--file", type=Path, required=True)
        child.add_argument("--jobs", type=int, default=1, choices=range(1, MAX_JOBS + 1))
    child = commands.add_parser("run-selected", help="Run an ordered selection of Studio tests")
    child.add_argument("--suite", action="append", required=True, help="Test ID. Repeat for each selected test.")
    target = child.add_mutually_exclusive_group()
    target.add_argument("--environment", type=Path, help="Explicit CI or test-operator profile")
    target.add_argument("--test-server", help="Choose a verified Docker test server for the saved source folder")
    child.add_argument("--keep-running", action="store_true")
    child.add_argument("--source", type=Path, help="Use this source folder instead of the saved selection")
    commands.add_parser("environment-template", help="Print an editable environment example (contains no credentials)")
    child = commands.add_parser("record-start")
    target = child.add_mutually_exclusive_group()
    target.add_argument("--environment", type=Path)
    target.add_argument("--test-server")
    child.add_argument("--source", type=Path, help="Use this source folder instead of the saved selection")
    child.add_argument("--role", action="append", required=True)
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
        launch(args.workspace, args.collection)
        return 0
    linux_commands = ("run", "run-selected", "plan-batch", "run-batch", "select-source", "test-servers",
                      "register-test-server", "docker-check")
    if os.name == "nt" and (args.command in linux_commands or args.command.startswith("record-") or
                            args.command == "plan" and not args.environment):
        try:
            return windows_relay(argv, args.workspace)
        except (OSError, subprocess.CalledProcessError):
            emit({"event": "error", "error": "Studio needs its WSL Linux environment and Docker Desktop integration on Windows."})
            return 1
    library = Collection(args.collection) if args.collection else Library(args.workspace)
    run_workspace = args.run_workspace or args.workspace
    try:
        if args.command == "list":
            emit({"suites": library.list()})
        elif args.command == "show":
            emit(library.get(args.suite))
        elif args.command == "validate":
            suite = library.get(args.suite)
            if is_driver_suite(suite):
                emit({"valid": True, "suite": args.suite, "validation": "driver manifest structure",
                      "studio_replay": False})
            else:
                validate(suite, runnable=True)
                emit({"valid": True, "suite": args.suite})
        elif args.command == "save":
            emit({"saved": str(library.save(read_json(args.file), replace=args.replace))})
        elif args.command == "export-regression":
            emit({"saved": str(export_regression(args.server_checkout, args.output))})
        elif args.command == "install-server-tools":
            from .server_tools import install_server_tools
            emit({"installed": str(install_server_tools(args.source))})
        elif args.command == "environment-template":
            emit(environment_template())
        elif args.command in ("select-source", "test-servers"):
            from .docker_runtime import list_servers
            source = select_source(args.workspace, args.source) if args.command == "select-source" else None
            try:
                servers = list_servers(args.workspace, start_if_needed=args.command == "test-servers" and args.start,
                                       emit=emit)
            except (ValueError, OSError) as exc:
                emit({"event": "test_servers", "source": source, "servers": [], "message": str(exc)})
                return int(source is None)
            else:
                emit({"event": "test_servers", "source": source, "servers": servers})
        elif args.command == "register-test-server":
            emit({"registered": str(register_setup(args.environment, replace=args.replace))})
        elif args.command == "docker-check":
            from .docker_check import build_and_test
            result = build_and_test(args.workspace, emit)
            emit(result)
            return int(not result["passed"])
        elif args.command == "batch-template":
            emit(batch_template())
        elif args.command == "run-selected":
            profile = environment(args.environment) if args.environment else None
            result = run_selected(args.suite, library, args.workspace, project=args.test_server,
                                  profile=profile, keep_running=args.keep_running, emit=emit,
                                  source=args.source, run_workspace=run_workspace)
            emit(result)
            return 130 if result["interrupted"] else int(not result["passed"])
        elif args.command in ("plan-batch", "run-batch"):
            prepared = prepare_batch(args.file, library)
            if args.command == "plan-batch":
                emit({"max_workers": args.jobs, "runs": [
                    {"id": job["id"], "suite": job["suite"]["id"], "environment": job["env"]["name"],
                     "exclusive_scopes": dict(job["scopes"])} for job in prepared
                ]})
            else:
                result = run_batch(prepared, run_workspace, args.jobs, emit)
                emit(result)
                return 130 if result["interrupted"] else int(not result["passed"])
        elif args.command in ("plan", "run"):
            suite = library.get(args.suite)
            if is_driver_suite(suite):
                raise ValueError("Driver manifests use the original server test harness. Select a Studio test for replay.")
            env = environment(args.environment) if args.environment else automatic_environment(
                args.workspace, suite["roles"], project=args.test_server, creation_roles=creation_roles(suite),
                source=getattr(args, "source", None))
            if args.command == "plan":
                emit(plan(suite, env))
            else:
                if args.environment or not suite["roles"]:
                    result = run_suite(suite, env, run_workspace, emit)
                else:
                    from .docker_runtime import active_server, plain_login
                    with active_server(env, keep_running=args.keep_running, emit=emit, login_only=plain_login(suite)):
                        result = run_suite(suite, env, run_workspace, emit)
                emit(result)
                return 0 if result["passed"] else 1
        else:
            from . import recording
            if args.command == "record-start":
                if args.environment:
                    result = recording.start(environment(args.environment), args.workspace, args.role, args.seconds)
                else:
                    from .docker_runtime import active_server
                    env = automatic_environment(args.workspace, args.role, project=args.test_server,
                                                recording=True, source=args.source)
                    with active_server(env, keep_running=True, emit=emit):
                        result = recording.start(env, args.workspace, args.role, args.seconds)
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
