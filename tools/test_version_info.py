"""Version validation, generated headers and isolated package imports; run with -B."""
import io
import py_compile
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.version_info import (
    check_library_version,
    source_version,
    validate_version,
    write_header,
)


class VersionTests(unittest.TestCase):
    def test_windows_components_and_invalid_versions(self):
        self.assertEqual(validate_version("2.3.4"), (2, 3, 4, 0))
        self.assertEqual(validate_version("0.65535.0"), (0, 65535, 0, 0))
        for value in (None, 123, "", "1.2", "1.2.3.4", "1.2.3-beta", "-1.2.3",
                      "+1.2.3", "1.2.3\n", " 1.2.3", "1.2.65536", "１.2.3"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_version(value)

    def test_header_cli_reads_changed_source_and_preserves_unchanged_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("tools/version_info.py", "clnch/clnch_resource.py", "clnch/clnch_strings.py",
                         "clnch/clnch_strings_ja.py"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, path)
            resource = root / "clnch/clnch_resource.py"
            resource.write_text(resource.read_text(encoding="utf-8").replace(
                f'clnch_version = "{source_version()}"', 'clnch_version = "2.3.4"'), encoding="utf-8")
            header = root / "obj/recraft_version.h"
            command = [sys.executable, "-B", str(root / "tools/version_info.py"), "--header", str(header)]
            subprocess.run(command, cwd=ROOT.parent, check=True)
            content = header.read_bytes()
            content.decode("ascii")
            self.assertIn(b'RECRAFT_VERSION_STRING "2.3.4"', content)
            self.assertIn(b"RECRAFT_VERSION_NUMBER 2,3,4,0", content)
            self.assertNotIn(b"\n", content.replace(b"\r\n", b""))
            timestamp = header.stat().st_mtime_ns
            subprocess.run(command, cwd=ROOT.parent, check=True)
            self.assertEqual(header.stat().st_mtime_ns, timestamp)
            write_header(header, "2.3.5")
            self.assertIn(b"2,3,5,0", header.read_bytes())
            with self.assertRaises(ValueError):
                write_header(header, "2.3.65536")
            self.assertIn(b"2,3,5,0", header.read_bytes())

    def test_packaged_version_cannot_fall_back_to_imported_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = root / "library.zip"
            resource = root / "clnch_resource.py"
            resource.write_text((ROOT / "clnch/clnch_resource.py").read_text(encoding="utf-8").replace(
                f'clnch_version = "{source_version()}"', 'clnch_version = "2.3.4"'), encoding="utf-8")
            with zipfile.ZipFile(library, "w") as archive:
                for name, source in (("clnch_resource", resource),
                                     ("clnch_strings", ROOT / "clnch/clnch_strings.py"),
                                     ("clnch_strings_ja", ROOT / "clnch/clnch_strings_ja.py")):
                    output = root / (name + ".pyc")
                    py_compile.compile(str(source), str(output), doraise=True, optimize=2)
                    archive.write(output, output.name)
            check_library_version(library, "2.3.4")
            with self.assertRaisesRegex(ValueError, "rebuild dist"):
                check_library_version(library, "2.3.5")
            with zipfile.ZipFile(library, "w") as archive:
                archive.writestr("unrelated.txt", "No version module")
            with self.assertRaises(subprocess.CalledProcessError):
                check_library_version(library, source_version())

    def test_bilingual_manual_tokens_preview_and_render_without_generated_includes(self):
        from docutils.core import publish_parts
        for lang in ("ja", "en"):
            with self.subTest(lang=lang):
                path = ROOT / f"docs/{lang}/index.txt"
                source = path.read_text(encoding="utf-8")
                self.assertEqual(source.count("{{APP_VERSION}}"), 1)
                for text in (source, source.replace("{{APP_VERSION}}", "2.3.4")):
                    warnings = io.StringIO()
                    html = publish_parts(text, source_path=str(path), writer="html",
                                         settings_overrides={"warning_stream": warnings,
                                                             "stylesheet_path": [],
                                                             "syntax_highlight": "none"})["whole"]
                    self.assertEqual(warnings.getvalue(), "")
                    self.assertIn("images/launcher_main.png", html)
                    self.assertIn("{{APP_VERSION}}" if text == source else "2.3.4", html)


if __name__ == "__main__":
    unittest.main()
