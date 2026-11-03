"""Check repository text files against the current .editorconfig rules."""
import configparser
import fnmatch
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_rules():
    rules = configparser.ConfigParser(interpolation=None)
    rules.read_string("[root]\n" + (ROOT / ".editorconfig").read_text(encoding="utf-8"))
    return rules


def properties(name, rules):
    result = {}
    for pattern in rules.sections():
        if pattern == "root":
            continue
        candidate = name if "/" in pattern else Path(name).name
        if fnmatch.fnmatchcase(candidate, pattern):
            result.update(rules[pattern])
    return result


def check_bytes(data, settings):
    charset = settings["charset"]
    if b"\0" in data and charset != "utf-16le":
        return None
    if charset == "utf-16le":
        assert data.startswith(b"\xff\xfe"), "UTF-16LE BOM required"
        text = data[2:].decode("utf-16le")
    elif charset == "utf-8-bom":
        assert data.startswith(b"\xef\xbb\xbf"), "UTF-8 BOM required"
        text = data[3:].decode("utf-8")
    elif charset == "unset":
        text = data.decode("latin1")
    else:
        assert charset == "utf-8", f"Unsupported charset: {charset}"
        assert not data.startswith(b"\xef\xbb\xbf"), "UTF-8 BOM is not allowed"
        text = data.decode("utf-8")
    newline = settings.get("end_of_line", "lf")
    assert newline in {"lf", "crlf"}, "Unsupported newline rule"
    if newline == "crlf":
        remainder = text.replace("\r\n", "")
        assert "\r" not in remainder and "\n" not in remainder, "CRLF required"
    else:
        assert "\r" not in text, "LF required"
    return text


def main():
    rules = load_rules()
    names = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
    ).decode("utf-8").split("\0")
    checked = 0
    errors = []
    for name in names:
        if not name or not (ROOT / name).is_file():
            continue
        try:
            if check_bytes((ROOT / name).read_bytes(), properties(name, rules)) is not None:
                checked += 1
        except (AssertionError, UnicodeError) as error:
            errors.append(f"{name}: {error}")
    assert not errors, "\n".join(errors)
    print(f"Checked {checked} text files: LF (UTF-16LE resources: CRLF) and encoding rules OK.")


if __name__ == "__main__":
    main()
