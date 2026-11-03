"""Message layout and input checks with native windows replaced; run with -B."""
import ast
import importlib.util
import sys
import unicodedata
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from test_modal_lifecycle import _cleanup_on_exit, _modal_dialog_scope

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "clnch"))


class Window:
    instances = []  # noqa: RUF012  # Shared test window registry.
    loop = None

    def __init__(self, **kwargs):
        self.options = kwargs
        self.x, self.y = kwargs["x"], kwargs["y"]
        self.w, self.h = kwargs["width"], kwargs["height"]
        self.draws = []
        self.closed = self.captured = self.destroyed = False
        self.instances.append(self)
    def getCharSize(self): return 10, 20
    def getClientSize(self): return self.w * 10 + 2, self.h * 20 + 2
    def width(self): return self.w
    def height(self): return self.h
    def getWindowRect(self): return self.x, self.y, self.x + self.w * 10 + 16, self.y + self.h * 20 + 36
    def getStringWidth(self, text):
        return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)
    def setPosSize(self, x, y, width, height, origin):
        self.w, self.h = width, height
        self.x = x - (width * 10 + 16) // 2 if origin & 1 else x
        self.y = y - (height * 20 + 36) // 2 if origin & 2 else y
    def charToClient(self, x, y): return x * 10 + 1, y * 20 + 1
    def putString(self, *args): self.draws.append(args)
    def show(self, visible): pass
    def quit(self): self.closed = True
    def setCapture(self): self.captured = True
    def releaseCapture(self): self.captured = False
    def messageLoop(self):
        if Window.loop: Window.loop(self)
    def destroy(self): self.destroyed = True


class MessageBoxTests(unittest.TestCase):
    def setUp(self):
        Window.instances, Window.loop = [], None
        ckit = ModuleType("ckit")
        ckit.__path__ = []
        ckit.TextWindow = Window
        ckit.getColor = lambda name: name
        ckit.Attribute = lambda **kwargs: kwargs
        tree = ast.parse((ROOT / "ckit/ckit_misc.py").read_text(encoding="utf-8-sig"))
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                     and n.name in ("splitLines", "getWindowWorkArea", "getWindowSizeLimits")]
        exec(compile(ast.Module(body=functions, type_ignores=[]), "layout-helpers", "exec"), ckit.__dict__)  # noqa: S102  # Execute isolated source under test.
        const = ModuleType("ckit.ckit_const")
        const.__dict__.update(ORIGIN_X_CENTER=1, ORIGIN_Y_CENTER=2, ORIGIN_X_LEFT=0, ORIGIN_Y_TOP=0,
            VK_UP=38, VK_DOWN=40, VK_PRIOR=33, VK_NEXT=34, VK_LEFT=37, VK_RIGHT=39, VK_RETURN=13, VK_ESCAPE=27,
            VK_HOME=36, VK_END=35)
        self.monitors = [((0, 0, 1920, 1080), (0, 0, 1920, 1040))]
        modules = {"ckit": ckit, "ckit.ckit_const": const,
            "pyauto": SimpleNamespace(Window=SimpleNamespace(getMonitorInfo=lambda: self.monitors)),
            "clnch_misc": SimpleNamespace(_modal_dialog_scope=_modal_dialog_scope, adjustWindowPosition=lambda *args, **kwargs: None)}
        ckit.pyauto = modules["pyauto"]
        modules["ckit.ckit_misc"] = SimpleNamespace(_cleanup_on_exit=_cleanup_on_exit)
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location("msgbox_test", ROOT / "clnch/clnch_msgbox.py")
            assert spec is not None and spec.loader is not None
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)

    def box(self, text, kind=0, **kwargs):
        return self.module.MessageBox(300, 200, None, False, kind, "Test", text, **kwargs)

    def test_wrap_preserves_newlines_and_display_width(self):
        box = self.box("a" * 100 + "\n\n" + "日本語" * 40)
        self.assertLessEqual(box.width(), 74)
        self.assertTrue(all(box.getStringWidth(line) <= 72 for line in box.message_lines))
        self.assertEqual("".join(box.message_lines), "a" * 100 + "日本語" * 40)
        self.assertIn("", box.message_lines)
        short = self.box("short")
        self.assertEqual((short.width(), short.height(), short.button_y), (20, 5, 3))
        self.assertEqual(self.box("").message_lines, [""])

    def test_scroll_is_bounded_and_buttons_remain_fixed(self):
        self.monitors = [((0, 0, 500, 300), (0, 0, 500, 300))]
        box = self.box("\n".join(f"line{i}" for i in range(100)))
        self.assertLessEqual(box.height() * 20 + 36, 300)
        button_y = box.button_y
        box.onKeyDown(34, 0)
        self.assertEqual(box.scroll_pos, box.visible_rows)
        box.onKeyDown(38, 0)
        self.assertEqual(box.scroll_pos, box.visible_rows - 1)
        box.onKeyDown(40, 0)
        box.onKeyDown(33, 0)
        self.assertEqual(box.scroll_pos, 0)
        box.onMouseWheel(0, 0, -1, 0)
        self.assertEqual(box.scroll_pos, 3)
        box._scroll(10000)
        self.assertEqual(box.scroll_pos + box.visible_rows, 100)
        box.draws.clear()
        box.paint()
        self.assertEqual(box.button_y, button_y)
        self.assertTrue(any(args[-1] == " OK " and args[1] == button_y for args in box.draws))
        self.assertTrue(any("続きあり" in args[-1] for args in box.draws))
        self.assertTrue(all(0 <= args[1] < box.height() for args in box.draws))
        box.onMouseWheel(0, 0, 1000, 0)
        self.assertEqual(box.scroll_pos, 0)

    def test_button_click_requires_press_and_release_on_same_button(self):
        for kind in (0, 1):
            box = self.box("test", kind, return_modkey=True)
            for button, label, column, width in box.buttons:
                box.closed = False
                x, y = box.charToClient(column, box.button_y)
                box.onLeftButtonUp(x, y, 0)
                self.assertFalse(box.closed)
                box.onLeftButtonDown(x, y, 0)
                self.assertTrue(box.captured)
                box.onLeftButtonUp(0, 0, 0)
                self.assertFalse(box.closed)
                self.assertFalse(box.captured)
                box.onLeftButtonDown(x, y, 0)
                box.onLeftButtonUp(x, y, 4)
                self.assertTrue(box.closed)
                self.assertEqual(box.getResult(), ({0: 1, 1: 2, 2: 3}[button], 4))

    def test_keyboard_results_unchanged(self):
        box = self.box("test", 1)
        box.onKeyDown(39, 0)
        self.assertEqual(box.focus, box.BUTTON_NO)
        box.onKeyDown(37, 0)
        self.assertEqual(box.focus, box.BUTTON_YES)
        box.onKeyDown(13, 0)
        self.assertEqual(box.getResult(), self.module.MSGBOX_RESULT_YES)
        for kind in (0, 1):
            box = self.box("test", kind)
            box.onKeyDown(27, 0)
            self.assertTrue(box.closed)
            self.assertEqual(box.getResult(), self.module.MSGBOX_RESULT_CANCEL)

    def test_home_end_scroll_body_without_changing_button_focus(self):
        self.monitors = [((0, 0, 500, 300), (0, 0, 500, 300))]
        box = self.box("\n".join(str(i) for i in range(100)), 1)
        box.onKeyDown(39, 0)
        box.onKeyDown(35, 0)
        self.assertEqual(box.scroll_pos, 100 - box.visible_rows)
        self.assertEqual(box.focus, box.BUTTON_NO)
        self.assertFalse(box.closed)
        box.onKeyDown(36, 0)
        self.assertEqual(box.scroll_pos, 0)
        self.assertEqual(box.focus, box.BUTTON_NO)
        self.assertFalse(box.closed)
        short = self.box("short")
        short.onKeyDown(35, 0)
        short.onKeyDown(36, 0)
        self.assertEqual(short.scroll_pos, 0)

    def test_popup_is_clamped_to_selected_monitor_work_area(self):
        self.monitors = [((0, 0, 800, 600), (0, 0, 800, 560)),
            ((-800, 0, 0, 600), (-800, 40, 0, 560))]
        parent = SimpleNamespace(getWindowRect=lambda: (-700, 250, -600, 350),
            isEnabled=lambda: True, enable=lambda enabled: None, activate=lambda: None)
        self.module.clnch_misc.adjustWindowPosition = lambda parent, box, **kwargs: box.setPosSize(
            -900, 500, box.width(), box.height(), 0)
        Window.loop = lambda box: box.onKeyDown(27, 0)
        self.module.popMessageBox(parent, 0, "test", "long " * 1000)
        box = Window.instances[-1]
        left, top, right, bottom = box.getWindowRect()
        self.assertGreaterEqual(left, -800)
        self.assertGreaterEqual(top, 40)
        self.assertLessEqual(right, 0)
        self.assertLessEqual(bottom, 560)
        self.assertTrue(box.destroyed)

    def test_popup_restores_parent_and_destroys_window_if_loop_fails(self):
        events = []
        parent = SimpleNamespace(getWindowRect=lambda: (100, 100, 200, 200),
            isEnabled=lambda: True, enable=lambda value: events.append(value), activate=lambda: events.append("activate"))
        def fail(box):
            raise RuntimeError("loop failed")
        Window.loop = fail
        with self.assertRaisesRegex(RuntimeError, "loop failed"):
            self.module.popMessageBox(parent, 0, "test", "message")
        self.assertEqual(events, [False, True, "activate"])
        self.assertTrue(Window.instances[-1].destroyed)


if __name__ == "__main__":
    unittest.main()
