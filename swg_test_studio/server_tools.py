"""Install the exact bundled tools into a separately selected SWG server tree."""
from pathlib import Path

from devtools.zones.studio_tool_bundle import MANIFEST, check_path, verify


BUNDLED_TOOLS = Path(__file__).resolve().parents[1] / "devtools"


def bundled_paths():
    return [BUNDLED_TOOLS / name for name in (MANIFEST, *sorted(verify(BUNDLED_TOOLS)))]


def install_server_tools(path):
    source = Path(path)
    if source.name.casefold() == "src":
        source = source.parent
    source = source.resolve(strict=True)
    if not all((source / marker).is_file() for marker in (
            "src/engine/server/application/CentralServer/Makefile.am",
            "src/game/server/application/SwgGameServer/Makefile.am")):
        raise ValueError("Choose the WhiteNGold server source folder or its src folder.")

    destination = check_path(source, "devtools")
    manifest = check_path(destination, MANIFEST)
    files = bundled_paths()
    # Publish the manifest last so a partially copied installation can be retried.
    files = files[1:] + files[:1]
    targets = []
    for original in files:
        target = check_path(destination, original.relative_to(BUNDLED_TOOLS).as_posix())
        data = original.read_bytes()
        if target.exists():
            if not target.is_file() or target.read_bytes() != data:
                raise ValueError("Existing server tool differs from the Studio bundle: " + str(target))
        else:
            targets.append((target, data))
    if manifest.is_file():
        verify(destination)
    elif destination.exists():
        expected = {destination / original.relative_to(BUNDLED_TOOLS) for original in files}
        if any(path.is_file() and path not in expected for path in destination.rglob("*")):
            raise ValueError("Use the existing server checkout tools. Studio will not mix the bundle with another tool tree.")
    for target, data in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
    verify(destination)
    return destination
