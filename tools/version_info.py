"""Generate and verify versions from clnch_resource.clnch_version."""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def validate_version(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value):
        raise ValueError("Version must contain three decimal integers: X.Y.Z")
    numbers = tuple(int(part) for part in value.split("."))
    if any(number > 65535 for number in numbers):
        raise ValueError("Version components must be between 0 and 65535")
    return (*numbers, 0)


def source_version():
    sys.path.insert(0, str(ROOT / "clnch"))
    try:
        import clnch_resource
    finally:
        sys.path.pop(0)
    value = clnch_resource.clnch_version
    validate_version(value)
    return value


def write_header(path, version):
    numbers = validate_version(version)
    content = ("// Generated from clnch_resource.clnch_version; do not edit.\r\n"
               f'#define RECRAFT_VERSION_STRING "{version}"\r\n'
               f'#define RECRAFT_VERSION_NUMBER {",".join(map(str, numbers))}\r\n').encode("ascii")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_bytes() != content:
        path.write_bytes(content)


def check_library_version(library, expected):
    validate_version(expected)
    # A fresh isolated process must import the packaged module, never the source tree.
    code = '''import sys
from pathlib import Path
library = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(library))
import clnch_resource
if Path(clnch_resource.__file__).parent != library:
    raise ValueError("Version module was not loaded from library.zip")
print(clnch_resource.clnch_version)
'''
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", code, str(Path(library).resolve())],
                            capture_output=True, text=True, check=True)
    actual = result.stdout.strip()
    if actual != expected:
        raise ValueError(f"{library}: version {actual!r} differs from {expected!r}; rebuild dist before archive")


def check_executable_version(executable, expected):
    validate_version(expected)
    subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-File",
                    str(ROOT / "tools/check_executable_version.ps1"),
                    "-Executable", str(Path(executable).resolve()), "-ExpectedVersion", expected], check=True)


def check_package_versions(package, expected):
    package = Path(package)
    check_library_version(package / "library.zip", expected)
    check_executable_version(package / "reclnch.exe", expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--header", type=Path)
    actions.add_argument("--package", type=Path)
    args = parser.parse_args()
    version = source_version()
    if args.header:
        write_header(args.header, version)
    elif args.package:
        check_package_versions(args.package, version)
        print(f"Version OK: {version}")
    else:
        print(version)


if __name__ == "__main__":
    main()
