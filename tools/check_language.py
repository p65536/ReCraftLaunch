"""Validate bundled wording, bytecode and bilingual distribution documents."""
import argparse
import ast
import importlib.util
import marshal
import re
import string
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_definitions(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    definitions = {}
    for index, node in enumerate(tree.body):
        if (index == 0 and isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            continue
        if (not isinstance(node, ast.Assign) or len(node.targets) != 1
                or not isinstance(node.targets[0], ast.Name)
                or not re.fullmatch(r"[A-Z][A-Z0-9_]*", node.targets[0].id)
                or not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str)):
            raise ValueError(f"{path}:{node.lineno}: expected a string constant definition")
        name = node.targets[0].id
        if name in definitions:
            raise ValueError(f"{path}:{node.lineno}: duplicate constant {name}")
        definitions[name] = node.value.value
    return definitions


def placeholders(value):
    return {name for _, name, _, _ in string.Formatter().parse(value) if name is not None}


def resolve_language(lang="ja", root=ROOT):
    if lang not in ("ja", "en"):
        raise ValueError(f"Invalid language: {lang!r}")
    standard = root / "clnch/clnch_strings_ja.py"
    source = root / f"clnch/clnch_strings_{lang}.py"
    reference = read_definitions(standard)
    translated = read_definitions(source)
    if reference.keys() != translated.keys():
        raise ValueError(f"{source}: missing {sorted(reference.keys() - translated.keys())}; "
                         f"extra {sorted(translated.keys() - reference.keys())}")
    for name, value in translated.items():
        if placeholders(value) != placeholders(reference[name]):
            raise ValueError(f"{source}: placeholders differ for {name}")
    return source


def check_library(library, root=ROOT):
    sources = [root / "clnch/clnch_strings.py", resolve_language("ja", root), resolve_language("en", root)]
    with zipfile.ZipFile(library) as archive:
        names = archive.namelist()
        wording = [name for name in names if Path(name).name.startswith("clnch_strings")]
        if sorted(wording) != sorted(source.name + "c" for source in sources):
            raise ValueError(f"{library}: unexpected wording modules: {wording}")
        for source in sources:
            data = archive.read(source.name + "c")
            if data[:4] != importlib.util.MAGIC_NUMBER:
                raise ValueError(f"{library}: Python bytecode version differs")
            actual = marshal.loads(data[16:])
            expected = compile(source.read_text(encoding="utf-8"), source.name, "exec", optimize=2)
            if (actual.co_code, actual.co_consts, actual.co_names) != (expected.co_code, expected.co_consts, expected.co_names):
                raise ValueError(f"{library}: wording differs from {source}; rebuild dist")


def check_distribution(package, root=ROOT):
    package = Path(package)
    check_library(package / "library.zip", root)
    for name in ("README.txt", "COMMANDS.md", "docs/index.html", "docs/language.txt"):
        if (package / name).exists():
            raise ValueError(f"Obsolete package file: {name}")
    for lang in ("ja", "en"):
        help_dir = package / "docs" / lang
        if not (help_dir / "index.html").is_file():
            raise FileNotFoundError(f"Bundled help is missing: {help_dir}")
        if (help_dir / "language.txt").read_text(encoding="utf-8").strip() != lang:
            raise ValueError(f"Help language differs: {help_dir}")
        for source, destination in (("readme.txt", f"README.{lang}.txt"), ("commands.md", f"COMMANDS.{lang}.md")):
            if (package / destination).read_bytes() != (root / "docs" / lang / source).read_bytes():
                raise ValueError(f"Package document differs: {destination}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path)
    parser.add_argument("--package", type=Path)
    args = parser.parse_args()
    if not args.library and not args.package:
        for lang in ("ja", "en"):
            resolve_language(lang)
    if args.library:
        check_library(args.library)
    if args.package:
        check_distribution(args.package)
    print("Wording OK: Japanese + English")


if __name__ == "__main__":
    main()
