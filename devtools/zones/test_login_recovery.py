#!/usr/bin/env python3
"""Build and exercise the native recovery admission component; no running server."""
from pathlib import Path
import argparse
import re
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[2]


def main(source=None, label="recovery", include_roots=(), native_required=False, gnu_cpp03=False, generated_include_root=None, execution_timeout=10):
    if not isinstance(execution_timeout,int) or not 1<=execution_timeout<=120:
        raise ValueError('Native probe execution timeout must be a bounded 1..120 seconds')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stlport-root", type=Path,
                        help="ELF64 STLport root containing stlport/ and lib/libstlport_gcc.a")
    parser.add_argument("--native-central", type=Path,
                        help="ELF64 CentralServer binary whose ldd-resolved libraries supply the native runtime")
    parser.add_argument("--native-source-root", type=Path,
                        help="matching Linux-native source snapshot containing src/; avoids compiling headers through a Windows mount")
    parser.add_argument("--native-static", type=Path, action="append", default=[],
                        help="matching static dependency from CentralServer's link (repeatable)")
    parser.add_argument("--native-library", type=Path, action="append", default=[],
                        help="additional ELF64 producer library required by the probe (repeatable)")
    parser.add_argument("--output", type=Path, help="save a linked ELF64 artifact instead of running the test; use a fresh path")
    parser.add_argument("--debug", action="store_true", help="run under gdb for a native-runtime failure")
    parser.add_argument("--runtime-baseline", action="store_true",
                        help="link an empty main against the same native libraries to isolate runtime faults")
    args = parser.parse_args()
    if native_required and not args.native_central:
        parser.error("this wire probe requires --native-central and --stlport-root")
    if bool(args.stlport_root) != bool(args.native_central):
        parser.error("--stlport-root and --native-central must be supplied together")
    if args.native_source_root and not args.native_central:
        parser.error("--native-source-root requires --native-central")
    compile_repo=REPO
    if args.native_source_root:
        compile_repo=args.native_source_root.resolve(strict=True)
        if str(compile_repo).startswith('/mnt/') or not (compile_repo/'src/engine').is_dir():
            parser.error("--native-source-root must be a Linux-native source snapshot containing src/engine")
    if args.native_static and not args.native_central:
        parser.error("--native-static requires --native-central")
    if args.native_library and not args.native_central:
        parser.error("--native-library requires --native-central")
    for library in args.native_library:
        if library.read_bytes()[:5] != b'\x7fELF\x02':
            parser.error("--native-library must name an ELF64 producer")
    if args.runtime_baseline and not args.native_central:
        parser.error("--runtime-baseline requires --native-central")
    with tempfile.TemporaryDirectory(prefix="swg-login-recovery-") as folder:
        binary = Path(folder) / "recovery"
        source = source or Path(__file__).with_suffix(".cpp")
        if args.runtime_baseline:
            source = Path(folder) / "baseline.cpp"
            source.write_text("int main() { return sizeof(void *) == 8 ? 0 : 1; }\n")
        command = ["g++", "-m64", "-std=gnu++03" if gnu_cpp03 else "-std=c++03", "-Wall", "-Wextra", "-Werror"]
        if generated_include_root is not None:
            generated=Path(generated_include_root).resolve(strict=True)
            if generated!=Path(source).resolve(strict=True).parent or str(generated).startswith('/mnt/'):
                raise ValueError('Generated dependency headers must share the Linux-native probe directory')
            command += ['-isystem',str(generated)]
        for root in include_roots:
            if args.native_source_root:
                root=compile_repo/root.relative_to(REPO)
            command += ["-isystem", str(root)]
        if native_required:
            command += ["-DLINUX=1", "-D_DEBUG=1"]
        if args.stlport_root:
            command += ["-isystem", str(args.stlport_root / "stlport")]
        else:
            command += ["-pedantic", "-D_GLIBCXX_DEBUG"]
        command += ["-I" + str(compile_repo / "src/engine/server/application/CentralServer/src/shared"),
                    "-I" + str(compile_repo / "src/engine/server/library/serverUtility/include/public"),
                    str(source), "-o", str(binary)]
        if args.stlport_root:
            output = subprocess.check_output(["ldd", str(args.native_central)], text=True)
            if "not found" in output:
                raise RuntimeError("Source the matching native library search paths before this test")
            resolved = dict(re.findall(r"^\s*(\S+) => (/\S+) \(", output, re.MULTILINE))
            dynamic = subprocess.check_output(["readelf", "-d", str(args.native_central)], text=True)
            needed = re.findall(r"\(NEEDED\).*Shared library: \[([^\]]+)\]", dynamic)
            if not needed or any(name not in resolved for name in needed):
                raise RuntimeError("Cannot resolve CentralServer's direct ELF dependencies")
            # ldd includes transitive dependencies. Linking all of them directly
            # changes loader/destructor ordering; retain the executable's actual
            # DT_NEEDED order and let each library own its existing dependencies.
            libraries = [resolved[name] for name in needed]
            command += ["-Wl,--no-as-needed", "-Wl,--start-group",
                        str(args.stlport_root / "lib/libstlport_gcc.a")]
            command += libraries + [str(path) for path in args.native_library + args.native_static]
            command += ["-Wl,--end-group", "-pthread"]
        subprocess.run(command, check=True)
        if args.output:
            if args.output.exists():
                raise RuntimeError("--output must be a fresh path")
            import shutil
            args.output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(binary, args.output)
            print(f"Built ELF64 artifact: {args.output}")
            return
        if args.debug:
            subprocess.run(["gdb", "-batch", "-ex", "set debuginfod enabled off",
                            "-ex", "run", "-ex", "bt", "--args", str(binary)],
                           cwd=folder, check=True, timeout=30)
        subprocess.run([str(binary)], cwd=folder, check=True, timeout=execution_timeout)
        if args.runtime_baseline:
            print("ELF64 native-runtime empty-main baseline passed, including static teardown.")
        elif args.native_central:
            print(f"ELF64 native-runtime {label} probe passed, including static teardown.")


if __name__ == "__main__":
    main()
