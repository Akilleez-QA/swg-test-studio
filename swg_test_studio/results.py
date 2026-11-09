"""Read Studio's saved results and bounded log previews for the desktop."""
from dataclasses import dataclass
import json
from pathlib import Path
import re

from .store import read_json


REPORT_LIMIT = 2 * 1024 * 1024
LOG_LIMIT = 256 * 1024
STEP_ID = re.compile(r"[a-z][a-z0-9_]{2,127}")
ACTION = re.compile(r"STUDIO_STEP (start|pass) ([1-9][0-9]?) ([a-z_]+)")
EXCEPTION = re.compile(r"(?:[\w.]*)(?:Error|Exception|Interrupt)(?::.*)?")


@dataclass(frozen=True)
class ResultSource:
    report: Path | None = None
    log: Path | None = None
    error: str = ""
    console: str = ""


@dataclass(frozen=True)
class ResultStep:
    name: str
    status: str
    reason: str = ""
    action: str = ""
    log: Path | None = None
    console: str = ""


def log_tail(path):
    if path is None:
        return ""
    try:
        with path.open("rb") as stream:
            size = stream.seek(0, 2)
            stream.seek(max(size - LOG_LIMIT, 0))
            data = stream.read(LOG_LIMIT).decode("utf-8", errors="replace")
    except OSError:
        return ""
    return ("[Earlier lines omitted. See the log file for the full output.]\n" + data
            if size > LOG_LIMIT else data)


def failed_action(log):
    active = ""
    for line in log.splitlines():
        match = ACTION.fullmatch(line)
        if match:
            state, index, label = match.groups()
            active = f"Action {index} · {label.replace('_', ' ').capitalize()}" if state == "start" else ""
    return active


def failure_reason(row, log):
    if row.get("error"):
        return str(row["error"])
    if row.get("timed_out"):
        return "The driver timed out while running this step."
    fallback = ""
    for line in reversed(log.splitlines()):
        if line.startswith("SCENARIO_FAILURE "):
            return line.removeprefix("SCENARIO_FAILURE ")
        if line.startswith("{"):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("event") == "error" and isinstance(event.get("error"), str):
                return event["error"].removeprefix("ValueError: ")
        if not fallback and (EXCEPTION.fullmatch(line) or line.startswith(("FAIL: ", "ERROR: ")) or
                             ".py: error: " in line):
            fallback = line
    if fallback:
        return fallback
    if row.get("exit_code") is not None:
        return f"The driver exited with code {row['exit_code']}. See the step log for details."
    return "See the log for details."


def local_artifact(directory, name):
    """Artifact names come from the report schema, and must stay in its directory."""
    target = (directory / name).resolve()
    if not target.is_relative_to(directory.resolve()):
        raise ValueError("A report references a file outside its results folder.")
    return target


def result_steps(source):
    if source.report is None:
        console = source.console or log_tail(source.log)
        return [ResultStep("Run setup", "Failed", failure_reason({"error": source.error}, console),
                           log=source.log, console=console)]
    report = read_json(source.report, max_bytes=REPORT_LIMIT)
    if not isinstance(report, dict) or not isinstance(report.get("cases"), list):
        raise ValueError("Choose a Studio test result.json or a batch-result.json report.")
    directory = source.report.parent
    manifest = local_artifact(directory, "manifest.json")
    planned = read_json(manifest, max_bytes=REPORT_LIMIT)["tests"] if manifest.is_file() else report["cases"]
    cases = {case["id"]: case for case in report["cases"]}
    steps = []
    if report.get("error"):
        steps.append(ResultStep("Run setup", "Failed", str(report["error"]), log=source.log, console=source.console))
    for entry in planned:
        name = entry["id"]
        if not STEP_ID.fullmatch(name):
            raise ValueError("The report contains an invalid step ID.")
        if name not in cases:
            steps.append(ResultStep(name, "Not run"))
            continue
        case = cases[name]
        log = local_artifact(directory, name + ".log")
        if case.get("passed") is True:
            steps.append(ResultStep(name, "Passed", log=log))
        else:
            preview = log_tail(log)
            steps.append(ResultStep(name, "Failed", failure_reason(case, preview),
                                    case.get("action") or failed_action(preview), log))
    if not any(step.status == "Failed" for step in steps) and (source.error or report.get("passed") is not True):
        steps.append(ResultStep("Run setup or cleanup", "Failed", source.error or "The run did not complete.",
                                log=source.log, console=source.console))
    return steps


def open_saved_report(path):
    report = read_json(path, max_bytes=REPORT_LIMIT)
    if isinstance(report, dict) and isinstance(report.get("cases"), list):
        return {str(report.get("suite", "Test")): ResultSource(report=path)}
    if not isinstance(report, dict) or not isinstance(report.get("runs"), list):
        raise ValueError("Choose a Studio test result.json or a batch-result.json report.")
    sources = {}
    for run in report["runs"]:
        name = run["id"]
        if not STEP_ID.fullmatch(name):
            raise ValueError("The batch report contains an invalid run ID.")
        if run.get("skipped"):
            continue
        directory = local_artifact(path.parent, name)
        result = local_artifact(directory, "runs")
        reports = list(result.glob("*/result.json"))
        report_path = local_artifact(directory, reports[0].relative_to(directory)) if len(reports) == 1 else None
        sources[name] = ResultSource(report_path, local_artifact(directory, "cli.jsonl"), run.get("error", ""))
    return sources
