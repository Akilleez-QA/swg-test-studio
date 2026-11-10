"""Resolve trusted bundled tools separately from each selected server source."""
from functools import cache
from importlib import import_module
from importlib.util import module_from_spec, spec_from_file_location
import os
from pathlib import Path
import sys

TOOLS_ROOT = Path(__file__).resolve().parents[1] / "devtools"
_spec = spec_from_file_location("swg_studio_tool_bundle", TOOLS_ROOT / "zones/studio_tool_bundle.py")
_bundle = module_from_spec(_spec)
_spec.loader.exec_module(_bundle)
SOURCE_ROOT_ENV = _bundle.SOURCE_ROOT_ENV


@cache
def verified_tool_root():
    _bundle.verify(TOOLS_ROOT)
    return TOOLS_ROOT


def bundled_paths():
    return [TOOLS_ROOT / name for name in (_bundle.MANIFEST, *sorted(_bundle.verify(TOOLS_ROOT)))]


def source_folder(path):
    source = Path(path)
    if source.name.casefold() == "src":
        source = source.parent
    source = source.resolve()
    if not all((source / marker).is_file() for marker in (
            "src/engine/server/application/CentralServer/Makefile.am",
            "src/game/server/application/SwgGameServer/Makefile.am")):
        raise ValueError("Choose the WhiteNGold server source folder or its src folder.")
    return source


def load_tool(relative):
    path = verified_tool_root() / relative
    directory = str(path.parent)
    if directory in sys.path:
        sys.path.remove(directory)
    sys.path.insert(0, directory)
    module = sys.modules.get(path.stem) or import_module(path.stem)
    if Path(module.__file__).resolve() != path:
        raise ValueError("Unexpected module loaded for Studio tool " + path.stem)
    return module


def server_profile(name=None):
    """A server profile by name (None: the default) from the verified bundled tool."""
    return load_tool("zones/server_profile.py").get(name)


def profile_of(env):
    return server_profile(env.get("profile"))


def tool_environment(source):
    return load_tool("zones/server_profile.py").child_environment(dict(os.environ, **{SOURCE_ROOT_ENV: str(source)}))
