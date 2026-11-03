"""Verify selected native origins and rejection of Debug CRT contamination."""
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from check_native_build import (
    NATIVE_FILES,
    check_release,
    check_runtime,
    copy_runtime,
    imported_dlls,
)
from native_test_support import (
    CONFIGURATION,
    NATIVE_NAMES,
    ROOT,
    RUN_DIR,
    NativeTestFinder,
)

sys.path[:0] = [str(ROOT), str(ROOT / "clnch"), str(RUN_DIR / "lib")]


class NativeBuildTests(unittest.TestCase):
    def test_source_directories_contain_no_native_outputs(self):
        for directory, stem in (("ckit", "ckitcore"), ("pyauto", "pyautocore")):
            for extension in ("pyd", "lib", "exp", "pdb", "ipdb", "iobj"):
                self.assertFalse((ROOT / directory / (stem + "." + extension)).exists())

    def test_selected_native_origins_and_crt(self):
        import ckit
        import clnch_native
        import pyauto

        self.assertIs(ckit.Window, sys.modules["ckit.ckitcore"].Window)
        self.assertIs(pyauto.Window, sys.modules["pyauto.pyautocore"].Window)
        self.assertIs(clnch_native, sys.modules["clnch_native"])
        for name in NATIVE_NAMES:
            path = Path(sys.modules[name].__file__).resolve()
            self.assertEqual(path.parent, RUN_DIR / "lib")
            self.assertEqual("ucrtbased.dll" in imported_dlls(path), CONFIGURATION == "Debug")

    def test_missing_selected_build_does_not_use_another_build(self):
        with tempfile.TemporaryDirectory() as directory, patch("native_test_support.RUN_DIR", Path(directory)):
            for name in NATIVE_NAMES:
                with self.subTest(name=name), self.assertRaises(FileNotFoundError):
                    NativeTestFinder().find_spec(name)

    def test_release_check_rejects_a_debug_extension(self):
        release = ROOT / "build/run/x64/Release"
        check_release(release)
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)
            shutil.copytree(release / "lib", app / "lib")
            for name in ("reclnch.exe", "python315.dll"):
                shutil.copy2(release / name, app / name)
            shutil.copy2(ROOT / "build/run/x64/Debug/lib/ckitcore.pyd", app / "lib/ckitcore.pyd")
            with self.assertRaisesRegex(ValueError, "Debug CRT in Release.*ckitcore"):
                check_release(app)

    def test_release_check_rejects_extra_binaries_in_lib_and_root(self):
        release = ROOT / "build/run/x64/Release"
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)
            shutil.copytree(release / "lib", app / "lib")
            for name in ("reclnch.exe", "python315.dll"):
                shutil.copy2(release / name, app / name)
            for name in ("lib/old.dll", "lib/old.pyd", "old.dll", "reclnch_d.exe", "old.pdb"):
                with self.subTest(name=name):
                    path = app / name
                    shutil.copy2(release / "lib/clnch_native.pyd", path)
                    with self.assertRaisesRegex(ValueError, "(file set|binary set) differs"):
                        check_release(app)
                    path.unlink()

    def test_release_check_rejects_wrong_architecture(self):
        release = ROOT / "build/run/x64/Release"
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)
            shutil.copytree(release / "lib", app / "lib")
            for name in ("reclnch.exe", "python315.dll"):
                shutil.copy2(release / name, app / name)
            executable = app / "reclnch.exe"
            data = bytearray(executable.read_bytes())
            pe = struct.unpack_from("<I", data, 0x3C)[0]
            struct.pack_into("<H", data, pe + 4, 0x14C)
            executable.write_bytes(data)
            with self.assertRaisesRegex(ValueError, "Not an x64 PE"):
                check_release(app)


class RuntimeFilesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.python = self.root / "Python"
        (self.python / "DLLs").mkdir(parents=True)
        for name in ("python315.dll", "DLLs/_socket.pyd", "DLLs/dependency.dll",
                     "DLLs/python.cat", "DLLs/libtommath.dll", "DLLs/_testinternal.pyd",
                     "DLLs/_socket_d.pyd", "DLLs/tk86t.dll", "DLLs/symbols.pdb"):
            (self.python / name).write_bytes(name.encode())
        self.run = self.root / "build/run/x64/Release"
        (self.run / "lib").mkdir(parents=True)
        for name in NATIVE_FILES:
            (self.run / "lib" / name).write_bytes(b"current native: " + name.encode())
        (self.run / "settings/scripts").mkdir(parents=True)
        for name in ("custom.py", "commands.json", "reclnch.ini", "scripts/personal.py"):
            (self.run / "settings" / name).write_text("personal", encoding="utf-8")

    def snapshot(self, directory):
        return {path.relative_to(directory).as_posix(): path.read_bytes()
                for path in directory.rglob("*") if path.is_file()}

    def test_copy_removes_stale_files_preserves_natives_and_settings_and_is_repeatable(self):
        before = self.snapshot(self.run)
        for name in ("old.dll", "old.pyd", "old.txt", "python.cat", "libtommath.dll", "_socket_d.pyd"):
            (self.run / "lib" / name).write_bytes(b"stale")
        (self.run / "lib/_socket.pyd").write_bytes(b"old same-name runtime")
        copy_runtime(self.run, self.python)
        check_runtime(self.run, self.python)
        after = self.snapshot(self.run)
        for name, data in before.items():
            self.assertEqual(after[name], data, name)
        self.assertEqual({path.name for path in (self.run / "lib").iterdir()},
                         NATIVE_FILES | {"_socket.pyd", "dependency.dll"})
        copy_runtime(self.run, self.python)
        self.assertEqual(self.snapshot(self.run), after)
        # A dependency removed from the input must disappear on the next copy.
        (self.python / "DLLs/dependency.dll").unlink()
        copy_runtime(self.run, self.python)
        self.assertFalse((self.run / "lib/dependency.dll").exists())
        check_runtime(self.run, self.python)

    def test_copy_before_native_build_does_not_fabricate_missing_extensions(self):
        for name in NATIVE_FILES:
            (self.run / "lib" / name).unlink()
        copy_runtime(self.run, self.python)
        with self.assertRaisesRegex(ValueError, "missing=.*ckitcore.pyd"):
            check_runtime(self.run, self.python)

    def test_copy_preserves_native_names_with_windows_case_variation(self):
        native = self.run / "lib/ckitcore.pyd"
        before = native.read_bytes()
        native.rename(native.with_name("CKITCORE.PYD"))
        copy_runtime(self.run, self.python)
        self.assertEqual(native.read_bytes(), before)

    def test_check_rejects_extra_missing_and_modified_runtime_files(self):
        copy_runtime(self.run, self.python)
        for name in ("extra.pyd", "extra.dll", "extra.txt"):
            path = self.run / "lib" / name
            path.write_bytes(b"extra")
            with self.assertRaisesRegex(ValueError, "extra=.*" + name):
                check_runtime(self.run, self.python)
            path.unlink()
        for name in ("python315.dll", "lib/_socket.pyd", "lib/dependency.dll"):
            path = self.run / name
            data = path.read_bytes()
            path.write_bytes(b"old runtime")
            with self.assertRaisesRegex(ValueError, "differs from source"):
                check_runtime(self.run, self.python)
            path.write_bytes(data)
        (self.run / "lib/_socket.pyd").unlink()
        with self.assertRaisesRegex(ValueError, "missing=.*_socket.pyd"):
            check_runtime(self.run, self.python)

    def test_source_cannot_overwrite_native_extensions_or_bundle_vc_runtime(self):
        before = self.snapshot(self.run)
        for name in ("ckitcore.pyd", "CKITCORE.PYD", "vcruntime140.dll", "python315.dll"):
            path = self.python / "DLLs" / name
            path.write_bytes(b"wrong source")
            with self.assertRaisesRegex(ValueError, "Unexpected Python runtime file"):
                copy_runtime(self.run, self.python)
            self.assertEqual(self.snapshot(self.run), before)
            path.unlink()

    def test_nested_directory_is_rejected_without_recursive_deletion(self):
        (self.run / "lib/old.dll").write_bytes(b"stale")
        (self.run / "lib/subdir").mkdir()
        (self.run / "lib/subdir/keep.txt").write_text("keep", encoding="utf-8")
        before = self.snapshot(self.run)
        with self.assertRaisesRegex(ValueError, "flat runtime directory"):
            copy_runtime(self.run, self.python)
        self.assertEqual(self.snapshot(self.run), before)

    def junction(self, link, target):
        result = subprocess.run([os.environ["COMSPEC"], "/d", "/c", "mklink", "/J", str(link), str(target)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.addCleanup(link.rmdir)

    def test_junction_in_lib_or_ancestor_cannot_redirect_deletion(self):
        outside = self.root / "outside"
        (outside / "lib").mkdir(parents=True)
        (outside / "lib/old.dll").write_bytes(b"keep")
        before = self.snapshot(outside)
        for location in (self.run / "lib/link", self.root / "redirect"):
            with self.subTest(location=location):
                self.junction(location, outside)
                target = self.run if location.parent.name == "lib" else location
                with self.assertRaisesRegex(ValueError, "links or reparse points"):
                    copy_runtime(target, self.python)
                self.assertEqual(self.snapshot(outside), before)

    def test_lib_junction_cannot_redirect_copy_or_deletion(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "old.dll").write_bytes(b"keep")
        alternate = self.root / "alternate"
        alternate.mkdir()
        self.junction(alternate / "lib", outside)
        with self.assertRaisesRegex(ValueError, "links or reparse points"):
            copy_runtime(alternate, self.python)
        self.assertEqual((outside / "old.dll").read_bytes(), b"keep")
        self.assertFalse((alternate / "python315.dll").exists())

    def test_file_symlinks_including_dangling_links_are_rejected_before_mutation(self):
        outside = self.root / "keep.dll"
        outside.write_bytes(b"keep")
        for relative, target in (("lib/old.dll", outside), ("lib/ckitcore.pyd", outside),
                                 ("python315.dll", outside), ("lib/absent.dll", self.root / "absent")):
            with self.subTest(relative=relative):
                path = self.run / relative
                original = path.read_bytes() if path.exists() else None
                if path.exists():
                    path.unlink()
                os.symlink(target, path)
                try:
                    with self.assertRaisesRegex(ValueError, "links or reparse points"):
                        copy_runtime(self.run, self.python)
                    self.assertEqual(outside.read_bytes(), b"keep")
                    self.assertTrue(path.is_symlink())
                finally:
                    path.unlink()
                    if original is not None:
                        path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
