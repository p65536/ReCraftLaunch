"""Synchronize runtime files and verify the Release native file set and imports."""
import argparse
import fnmatch
import shutil
import stat
import struct
from pathlib import Path

PYTHON_DIR = Path(__file__).absolute().parent.parent / "Python315/tools"
NATIVE_FILES = {"ckitcore.pyd", "pyautocore.pyd", "clnch_native.pyd"}
PYTHON_IGNORES = (
    "tcl*.*", "tk*.*", "_tk*.*", "*.pdb", "*_d.pyd", "*_d.dll",
    "*_test.pyd", "_test*.pyd", "*.ico", "*.lib", "libtommath.dll", "python.cat",
)


def check_plain_path(path):
    path = Path(path).absolute()
    for item in (*reversed(path.parents), path):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError(f"Generated/runtime paths must not use links or reparse points: {item}")


def flat_files(directory):
    check_plain_path(directory)
    files = {}
    for path in sorted(Path(directory).iterdir()):
        check_plain_path(path)
        if not path.is_file():
            raise ValueError(f"Expected a flat runtime directory, found: {path}")
        files[path.name] = path
    return files


def runtime_sources(python_dir=PYTHON_DIR):
    python_dir = Path(python_dir)
    files = {name: path for name, path in flat_files(python_dir / "DLLs").items()
             if not any(fnmatch.fnmatch(name.lower(), pattern) for pattern in PYTHON_IGNORES)}
    for name, path in files.items():
        if (name.lower() in NATIVE_FILES or name.lower() == "python315.dll"
                or Path(name).suffix.lower() not in {".pyd", ".dll"}
                or name.lower().startswith(("vcruntime", "msvcp", "concrt", "vccorlib"))):
            raise ValueError(f"Unexpected Python runtime file: {path}")
    check_plain_path(python_dir / "python315.dll")
    if not (python_dir / "python315.dll").is_file():
        raise FileNotFoundError(python_dir / "python315.dll")
    return files


def copy_runtime(directory, python_dir=PYTHON_DIR):
    directory = Path(directory)
    sources = runtime_sources(python_dir)
    check_plain_path(directory / "python315.dll")
    if (directory / "python315.dll").exists() and not (directory / "python315.dll").is_file():
        raise ValueError(f"Expected a runtime file: {directory / 'python315.dll'}")
    check_plain_path(directory / "lib")
    existing = flat_files(directory / "lib") if (directory / "lib").exists() else {}
    # Native builds already wrote these three PYDs here; never remove or overwrite them.
    for name, path in existing.items():
        if name not in sources and name.lower() not in NATIVE_FILES:
            path.unlink()
    (directory / "lib").mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(python_dir) / "python315.dll", directory / "python315.dll")
    for name, source in sources.items():
        shutil.copy2(source, directory / "lib" / name)


def check_runtime(directory, python_dir=PYTHON_DIR):
    directory = Path(directory)
    sources = runtime_sources(python_dir)
    actual = flat_files(directory / "lib")
    expected = sources.keys() | NATIVE_FILES
    if actual.keys() != expected:
        raise ValueError(f"Runtime file set differs: extra={sorted(actual.keys() - expected)}, "
                         f"missing={sorted(expected - actual.keys())}")
    for name, source in {"python315.dll": Path(python_dir) / "python315.dll", **sources}.items():
        destination = directory / name if name == "python315.dll" else actual[name]
        check_plain_path(destination)
        if destination.read_bytes() != source.read_bytes():
            raise ValueError(f"Python runtime file differs from source: {destination}")


def imported_dlls(path):
    data = Path(path).read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[:2] != b"MZ" or data[pe:pe + 4] != b"PE\0\0":
        raise ValueError(f"Not a PE file: {path}")
    machine, count, _, _, _, optional_size = struct.unpack_from("<HHIIIH", data, pe + 4)
    optional = pe + 24
    if machine != 0x8664 or struct.unpack_from("<H", data, optional)[0] != 0x20B:
        raise ValueError(f"Not an x64 PE file: {path}")
    sections = [struct.unpack_from("<8sIIII", data, optional + optional_size + 40 * i)
                for i in range(count)]

    def offset(rva):
        for _, virtual_size, address, raw_size, raw in sections:
            if address <= rva < address + max(virtual_size, raw_size):
                return raw + rva - address
        raise ValueError(f"Invalid PE RVA in {path}: {rva}")

    imports = struct.unpack_from("<I", data, optional + 120)[0]
    result = set()
    if imports:
        descriptor = offset(imports)
        while any(struct.unpack_from("<5I", data, descriptor)):
            name = offset(struct.unpack_from("<I", data, descriptor + 12)[0])
            result.add(data[name:data.index(b"\0", name)].decode("ascii").lower())
            descriptor += 20
    return result


def check_release(directory):
    directory = Path(directory)
    check_runtime(directory)
    root_binaries = {path.name for path in directory.iterdir()
                     if path.suffix.lower() in {".exe", ".dll", ".pyd", ".pdb", ".lib", ".exp", ".obj", ".ilk"}}
    if root_binaries != {"reclnch.exe", "python315.dll"}:
        raise ValueError(f"Release root binary set differs: {sorted(root_binaries)}")
    binaries = [directory / "reclnch.exe", *(directory / "lib").glob("*.pyd"),
                *(directory / "lib").glob("*.dll"), directory / "python315.dll"]
    for binary in binaries:
        check_plain_path(binary)
        imports = imported_dlls(binary)
        debug = {dll for dll in imports
                 if dll == "ucrtbased.dll" or dll.startswith(("vcruntime", "msvcp", "msvcr"))
                 and dll.endswith("d.dll")}
        if debug:
            raise ValueError(f"Debug CRT in Release: {binary}: {sorted(debug)}")
        if any(dll.startswith("python") and dll.endswith(".dll") and dll != "python315.dll" for dll in imports):
            raise ValueError(f"Unexpected Python DLL import: {binary}: {sorted(imports)}")
    print(f"Release native imports OK: {len(binaries)} x64 binaries")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    check_release(parser.parse_args().directory)
