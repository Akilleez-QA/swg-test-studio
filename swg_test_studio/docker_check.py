"""Build and test Studio in a disposable, positively identified Docker image."""
from pathlib import Path
import re
import secrets
import subprocess

from .docker_runtime import docker, require_docker
from .store import APP, write_json


LABEL = "io.swg.test-studio.check"
IMAGE_ID = re.compile(r"sha256:[a-f0-9]{64}\Z")


def run_logged(args, path, timeout):
    with path.open("xb") as log:
        return subprocess.run(["docker", *args], stdin=subprocess.DEVNULL, stdout=log,
                              stderr=subprocess.STDOUT, timeout=timeout).returncode


def owned_image(tag, token):
    template = '{{.Id}} {{index .Config.Labels "' + LABEL + '"}}'
    result = subprocess.run(["docker", "image", "inspect", "--format", template, tag],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        if "No such image" in result.stderr:
            return None
        raise ValueError("Docker could not verify the temporary Studio image.")
    image, _, label = result.stdout.strip().partition(" ")
    if label != token or not IMAGE_ID.fullmatch(image):
        raise ValueError("Studio refused to remove an image without its build label.")
    return image


def build_and_test(workspace, emit):
    require_docker()
    token = secrets.token_hex(8)
    tag = "swg-test-studio-check:" + token
    root = Path(workspace).absolute() / "docker-checks" / token
    root.mkdir(mode=0o700, parents=True)
    report = {"schema_version": 1, "passed": False, "image_removed": False, "evidence": str(root)}
    try:
        if owned_image(tag, token):
            raise ValueError("The temporary Studio image name is already in use.")
        emit({"event": "studio_docker_build", "evidence": str(root)})
        report["build_exit"] = run_logged(
            ["build", "--platform", "linux/amd64", "--label", LABEL + "=" + token, "--tag", tag, str(APP)],
            root / "build.log", timeout=900)
        if report["build_exit"] == 0:
            image = owned_image(tag, token)
            if not image:
                raise ValueError("Docker did not produce the expected Studio image.")
            report["image"] = image
            emit({"event": "studio_docker_test", "evidence": str(root)})
            report["test_exit"] = run_logged(
                ["run", "--rm", "--pull", "never", "--platform", "linux/amd64", "--network", "none",
                 "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,noexec", "--cap-drop", "ALL",
                 "--security-opt", "no-new-privileges:true", image],
                root / "test.log", timeout=300)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        report["error"] = str(exc)
    finally:
        try:
            image = owned_image(tag, token)
            if image:
                docker("image", "rm", tag)
            report["image_removed"] = owned_image(tag, token) is None
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            report["cleanup_error"] = str(exc)
        report["passed"] = report.get("test_exit") == 0 and report["image_removed"]
        write_json(root / "result.json", report)
    return {"event": "studio_docker_result", **report}
