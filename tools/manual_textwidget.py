"""Interactive TextWidget check: run with Python315/tools/python.exe -B; close with X."""
import sys
from pathlib import Path
from unittest.mock import patch

from native_test_support import RUN_DIR

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "clnch"), str(RUN_DIR / "lib")]
sys._clnch_app_dir = str(ROOT)

import clnch_text

import ckit
from ckit import ckit_theme

clnch_text.initialize()


class ManualWindow(ckit.TextWindow):
    def __init__(self, show=True):
        self.edit = None
        super().__init__(width=80, height=24, title="TextWidget manual check", title_bar=True,
                         sysmenu=True, resizable=True, show=False, caret=True,
                         font_name="MS Gothic", font_size=16,
                         bg_color=ckit.getColor("bg"),
                         activate_handler=self.onActivate,
                         size_handler=self.onSize,
                         close_handler=self.quit, keydown_handler=self.onKeyDown,
                         char_handler=self.onChar)
        self.command = ckit.CommandMap(self)
        self.edit = ckit.TextWidget(self, 0, 0, self.width(), self.height())
        ckit.Keymap.init()
        self.edit.keymap = ckit.Keymap()
        bindings = {
            "Left": "CursorLeft", "Right": "CursorRight", "Up": "CursorUp", "Down": "CursorDown",
            "Home": "CursorLineBegin", "End": "CursorLineEnd",
            "S-Left": "SelectLeft", "S-Right": "SelectRight", "S-Up": "SelectUp", "S-Down": "SelectDown",
            "PageUp": "CursorPageUp", "PageDown": "CursorPageDown",
            "Return": "InsertReturn", "Back": "DeleteCharLeft", "Delete": "DeleteCharRight",
            "C-A": "SelectDocument", "C-Z": "Undo", "C-Y": "Redo", "Escape": "SelectCancel",
        }
        for key, name in bindings.items():
            self.edit.keymap[key] = getattr(self.edit, "command_" + name)
        self.edit.paint()
        if show:
            self.show(True)
            self.activate()

    def onActivate(self, active):
        if self.edit:
            self.edit.enableCursor(active)
            if not active:
                self.setCursorPos(-1, -1)
            self.edit.paint()

    def onSize(self, width, height):
        if self.edit:
            self.edit.setPosSize(0, 0, width, height)
            self.edit.paint()

    def onKeyDown(self, vk, mod):
        return self.edit.onKeyDown(vk, mod)

    def onChar(self, ch, mod):
        self.edit.onChar(ch, mod)

    def executeCommand(self, name, info):
        return self.edit.executeCommand(name, info)


def main():
    ckit.registerWindowClass("ReCraftLaunchTextWidgetCheck")
    ckit.setTheme("black", {})
    get_color = ckit_theme.getColor
    def color(name, section="COLOR"):
        return get_color(name, section) if ckit_theme.ini.has_option(section, name) else get_color("fg")
    # Supply the same missing editor colors as the drawing tests; do not change theme files.
    with patch.object(ckit_theme, "getColor", color):
        ckit.TextWidget.updateColor()
        window = ManualWindow()
        try:
            window.messageLoop()
        finally:
            window.edit.destroy()
            window.destroy()
    print("TextWidget closed normally.")


if __name__ == "__main__":
    main()
