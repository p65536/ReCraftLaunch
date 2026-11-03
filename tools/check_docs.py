"""Check generated documentation files, local references, and HTML anchors."""

import argparse
import ast
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.anchors = set()
        self.text = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ("href", "src") and value is not None:
                self.links.append(value)
            if value is not None and (name == "id" or (tag == "a" and name == "name")):
                self.anchors.add(value)

    def handle_data(self, data):
        self.text.append(data)

    def handle_endtag(self, tag):
        if tag in ("p", "div", "pre", "li", "td", "tr"):
            self.text.append("\n")


def check_licenses(text):
    sources = (
        ("ReCraftLaunch", "recraftlaunch", "LICENSE.md"),
        ("CraftLaunch", "craftlaunch", "licenses/craftlaunch_LICENSE.md"),
        ("ckit", "ckit", "ckit/LICENSE.md"),
        ("pyauto", "pyauto", "pyauto/LICENSE.md"),
        ("Python", "python", "licenses/python_LICENSE.txt"),
        ("Expat", "expat", "licenses/expat_LICENSE.txt"),
    )
    sections = re.findall(r"<h1\b[^>]*>(.*?)</h1>(.*?)(?=<h1\b|\Z)", text, re.DOTALL)
    assert len(sections) == len(sources), "Expected six license sections"
    for (heading, body), (name, anchor, source) in zip(sections, sources):
        title = Links()
        title.feed(heading)
        assert "".join(title.text).strip() == name, f"License heading/order differs: {name}"
        assert anchor in title.anchors, f"Missing license anchor: {anchor}"
        content = Links()
        content.feed(body)
        original = (root / source).read_text(encoding="utf-8-sig")
        # HTML changes whitespace; compare every word and punctuation mark of the complete original.
        assert " ".join(original.split()) in " ".join("".join(content.text).split()), (
            f"Incomplete or changed license text: {name}"
        )


root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("directory", nargs="?", type=Path)
parser.add_argument("--lang", choices=("ja", "en"))
args = parser.parse_args()
output = args.directory.resolve() if args.directory else root / "docs/html" / (args.lang or "ja")
language = (output / "language.txt").read_text(encoding="utf-8").strip()
assert language in ("ja", "en"), f"Invalid help language: {language}"
assert args.lang is None or language == args.lang, f"Unexpected help language: {language}"
rst_pages = ("index.html", "changes.html", "differences.html", "command_json.html")
for name in (*rst_pages, "commands.html", "extensions.html", "licenses.html", "topics.html",
             "pyauto_native.html", "ckit_native.html", "clnch_native_api.html"):
    assert (output / name).is_file(), f"Missing generated page: {name}"

pages = list(output.rglob("*.html"))
parsed = {}
references = 0
anchors = 0
referenced_files = set()
for page in pages:
    text = page.read_text(encoding="utf-8")
    assert 'class="system-message"' not in text, f"Docutils diagnostic in {page.name}"
    links = Links()
    links.feed(text)
    parsed[page.resolve()] = links
    if page.name == "licenses.html":
        check_licenses(text)
    if page.name.startswith("group__"):
        assert '<table class="memberdecls">' in text, f"Empty API group: {page.name}"
        assert page.with_suffix(".js").is_file(), f"Missing API group data: {page.name}"
    if page.name in rst_pages:
        assert '<div class="rst-content">' in text, f"Missing RST container: {page.name}"
        assert '<h1 class="title">' not in text, f"Repeated document title: {page.name}"
        assert "<style" not in text, f"Embedded stylesheet in {page.name}"
        assert 'href="rst2html_pygments.css"' in text, f"Missing document stylesheet: {page.name}"
    if page.name == "commands.html":
        assert '<table class="markdownTable' in text, "Missing rendered operation table"
    if page.name == "extensions.html":
        source = (root / f"docs/{language}/extensions.md").read_text(encoding="utf-8")
        assert text.count('<div class="fragment">') == source.count("<!-- example: "), (
            "Missing rendered extension examples"
        )
        for topic in ("mainwindow", "command", "listwindow", "threadutil", "subprocess", "widget", "textwidget", "pyautoinput"):
            assert f"group__{topic}.html" in links.links, f"Missing extension API link: {topic}"
        assert "pyauto_native.html" in links.links, "Missing native pyauto reference"
        for native_page in ("ckit_native.html", "clnch_native_api.html"):
            assert native_page in links.links, f"Missing native reference: {native_page}"
        assert "topics.html" in links.links, "Missing extension API index link"
        assert "command_json.html" in links.links, "Missing extension JSON format link"
    if page.name == "pyauto_native.html":
        native = (root / "pyauto/pyautocore/pyautocore.cpp").read_text(encoding="utf-8-sig")
        for table, prefix in (("Window_methods", "Window"), ("Image_methods", "Image"),
                              ("Input_methods", "Input"), ("Hook_methods", "Hook"), ("pyauto_funcs", "pyauto")):
            body = re.search(r"static PyMethodDef " + table + r"\[\] = \{(.*?)\};", native, re.DOTALL)
            assert body is not None, f"Missing native registration table: {table}"
            for method in re.findall(r'\{"(\w+)"', body[1]):
                assert f"{prefix}.{method}(" in text, f"Missing native API: {prefix}.{method}"
        for attribute in set(re.findall(r'wcscmp\(attrname, L"(\w+)"\)', native)):
            assert f'<span class="tt">{attribute}' in text, f"Missing Hook callback: {attribute}"
    if page.name in ("ckit_native.html", "clnch_native_api.html"):
        is_ckit = page.name == "ckit_native.html"
        native_path = "ckit/ckitcore/ckitcore.cpp" if is_ckit else "clnch_native/clnch_native.cpp"
        native = (root / native_path).read_text(encoding="utf-8-sig")
        tables = re.findall(r"static PyMethodDef (\w+)\[\]\s*=\s*\{(.*?)\};", native, re.DOTALL)
        assert tables, f"No native registrations in {native_path}"
        for table, body in tables:
            prefix = table.removesuffix("_methods") if table.endswith("_methods") else (
                "ckit" if is_ckit else "clnch_native")
            for method in re.findall(r'\{"(\w+)"', body):
                assert f"{prefix}.{method}(" in text, f"Missing native API: {prefix}.{method}"
        if is_ckit:
            for name in re.findall(r'PyModule_AddObject\(m, "(\w+)"', native):
                entry = "Image.fromBytes(" if name == "Image" else f"ckit.{name}("
                assert entry in text, f"Missing native construction entry: {name}"
            for name in set(re.findall(r'"(\w+_handler)"', native)):
                assert name in text, f"Missing native callback: {name}"
            for name in set(re.findall(r'strcmp\(attr_name, "(\w+)"\)', native)):
                assert re.search(r"\b" + name + r"\b", text), f"Missing native attribute: {name}"

for name, members in {
    "group__command.js": ("CommandInfo", "NamedCommand", "CommandMap", "CommandSequence", "KeyEvent", "Keymap"),
    "group__widget.js": ("TextWindow", "Dialog", "Widget", "ButtonWidget", "CheckBoxWidget", "ChoiceWidget",
                         "ColorWidget", "HotKeyWidget", "EditWidget", "TimeWidget", "ProgressBarWidget"),
    "group__textwidget.js": ("Token", "Lexer", "TextLexer", "RegexLexer", "CompletionResult", "Completion",
                             "WordCompletion", "Mode", "TextMode", "Point", "Selection", "Document", "Search", "TextWidget"),
    "group__pyautoinput.js": ("KeyDown", "KeyUp", "Key", "Char", "MouseMove", "MouseLeftDown", "MouseLeftUp",
                         "MouseLeftClick", "MouseRightDown", "MouseRightUp", "MouseRightClick", "MouseMiddleDown",
                         "MouseMiddleUp", "MouseMiddleClick", "MouseWheel", "MouseHorizontalWheel"),
    "group__misc.js": ("HugeFile", "HugeBinaryFile", "HugeTextFile"),
    "classclnch__mainwindow_1_1_main_window.js": (
        "configure", "commandLine", "registerStatusBar", "unregisterStatusBar", "setStatusMessage", "clearStatusMessage"),
    "classclnch__listwindow_1_1_list_window.js": ("__init__", "configure", "getResult"),
    "classckit_1_1ckit__widget_1_1_edit_widget.js": (
        "__init__", "insertText", "setText", "getText", "setSelection", "getSelection", "undo", "redo", "destroy"),
    "classckit_1_1ckit__textwidget_1_1_document.js": (
        "__init__", "readFile", "writeFile", "clearModified", "setMode", "updateSyntaxContext", "updateSyntaxTokens"),
    "classckit_1_1ckit__textwidget_1_1_text_widget.js": (
        "__init__", "configure", "setDocument", "point", "getText", "modifyText", "setSelection", "atomicUndoBegin",
        "atomicUndoEnd", "undo", "redo", "search", "popupList", "destroy", "command_SelectDocument", "command_InsertReturn"),
}.items():
    index = (output / name).read_text(encoding="utf-8")
    for member in members:
        assert f'"{member}"' in index, f"Missing documented API member {name}: {member}"

constant_index = (output / "group__pyautoconst.js").read_text(encoding="utf-8")
for node in ast.parse((root / "pyauto/pyauto_const.py").read_text(encoding="utf-8")).body:
    if isinstance(node, ast.Assign):
        name = node.targets[0].id
        assert f'"pyauto.pyauto_const.{name}"' in constant_index, f"Missing pyauto constant: {name}"

for page in pages:
    links = parsed[page.resolve()]
    for link in links.links:
        url = urlsplit(link)
        if url.scheme or url.netloc:
            continue
        target = page.parent / unquote(url.path) if url.path else page
        assert target.is_file(), f"{page.name}: missing local reference {link}"
        assert target.suffix.lower() not in (".md", ".txt"), f"{page.name}: unrendered document link {link}"
        referenced_files.add(target.resolve())
        if url.path:
            references += 1
        if url.fragment and target.resolve() in parsed:
            assert unquote(url.fragment) in parsed[target.resolve()].anchors, (
                f"{page.name}: missing anchor {link}"
            )
            anchors += 1

for image in (root / f"docs/{language}/images").iterdir():
    if image.is_file() and image.suffix != ".pdn":
        copied = output / "images" / image.name
        assert copied.read_bytes() == image.read_bytes(), f"Image copy differs: {image.name}"
        assert copied.resolve() in referenced_files or (output / image.name).resolve() in referenced_files, (
            f"Unused documentation image: {image.name}"
        )

assert (output / "rst2html_pygments.css").read_bytes() == (
    root / "tools/rst2html_pygments.css"
).read_bytes(), "Document stylesheet copy differs"

print(f"Checked {len(pages)} HTML pages, {references} local file references, "
      f"{anchors} anchors, and image/stylesheet copies.")
