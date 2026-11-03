"""Console lifecycle checks with Win32 activation/focus replaced; no GUI is opened."""
import ast
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "clnch"))
import clnch_inisettings as ini_settings


def load_class(filename, name, methods, namespace):
    tree = ast.parse((ROOT / "clnch" / filename).read_text(encoding="utf-8"))
    node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
    selected = ast.ClassDef(name=name, bases=[ast.Name(id="Base", ctx=ast.Load())], keywords=[],
                            body=[method for method in node.body if isinstance(method, ast.FunctionDef)
                                  and method.name in methods], decorator_list=[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[selected], type_ignores=[])),  # noqa: S102  # Execute isolated source under test.
                 filename, "exec"), namespace)
    return namespace[name], node


class ConsoleVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.foreground = None
        self.focus = None
        self.settings = {("MISC", "inactive_behavior"): "hide"}
        harness = self

        class Base:
            def __init__(self, hwnd, owner=None, visible=True):
                self.hwnd, self.owner, self.visible = hwnd, owner, visible
                self.active = False
                self.enabled = True

            def getHWND(self): return self.hwnd
            def getOwner(self): return self.owner
            def isVisible(self): return self.visible
            def isEnabled(self): return self.enabled
            def paint(self, *args): pass
            def width(self): return 80
            def height(self): return 20
            def show(self, show, activate=True):
                self.visible = show
                harness.events.append(("show", self.hwnd, show))
                if show and activate:
                    self.activate()

            def activate(self):
                if harness.foreground is self:
                    return
                previous = harness.foreground
                # WM_ACTIVATE(False) arrives before the next window is active.
                if previous:
                    previous._onActivate(False)
                harness.foreground = self
                self._onActivate(True)

            def _onActivate(self, active): self.active = active
            def restore(self): self.show(True)
            def foreground(self): pass
            def removeKeyMessage(self): pass
            def quit(self): harness.events.append("quit")

        def set_focus(hwnd):
            self.focus = hwnd

        self.namespace = {
            "ini_settings": ini_settings,
            "Base": Base, "ckit": SimpleNamespace(
                JobQueue=SimpleNamespace(checkAll=lambda: None), TextWindow=Base, KeyEvent=lambda vk, mod: (vk, mod), CommandInfo=SimpleNamespace),
            "pyauto": SimpleNamespace(Window=SimpleNamespace(getForeground=lambda: self.foreground)),
            "clnch_misc": SimpleNamespace(adjustWindowPosition=lambda *args, **kwargs: None),
            "clnch_ini": SimpleNamespace(
                get=lambda section, key, default: self.settings.get((section, key), default),
                set=lambda section, key, value: self.settings.__setitem__((section, key), value),
                write=lambda: self.events.append("write")),
            "_SetFocus": set_focus,
            "VK_RETURN": 13, "VK_ESCAPE": 27, "VK_F10": 121, "MODKEY_CTRL": 2,
            "VK_A": 65, "VK_C": 67,
            "VK_UP": 38, "VK_DOWN": 40, "VK_PRIOR": 33, "VK_NEXT": 34,
            "VK_LEFT": 37, "VK_RIGHT": 39, "VK_F1": 112,
        }
        main_class, _ = load_class("clnch_mainwindow.py", "MainWindow", {
            "_onActivate", "isLauncherActive", "onTimer", "saveState", "hotkey_Activate",
            "command_ConsoleOpen", "command_ConsoleClose", "command_ConsoleToggle",
            "command_ClearInput", "inactiveMessageLoop", "topLevelMessageLoop",
        }, self.namespace)
        console_class, _ = load_class("clnch_consolewindow.py", "ConsoleWindow", {
            "show", "isOwnerActive", "onParentActivate", "syncVisibility", "onTimerAutoShow",
            "_onActivate", "_onClose", "_onKeyDown", "rectText",
        }, self.namespace)
        self.main = main_class(1)
        self.main.initialized = True
        self.main._launcher_active = False
        self.main.synccall = SimpleNamespace(check=lambda: None)
        self.main.input_settings = {"CLEAR_ON_DEACTIVATE": True, "HISTORY_MODE": "off"}
        self.main.commandLineHistorySave = lambda: None
        self.text = "draft"
        self.main.commandline_edit = SimpleNamespace(
            getText=lambda: self.text, setText=self.set_text, clear=lambda: self.set_text(""),
            onWindowActivate=lambda active: None, onKeyDown=lambda vk, mod: False)
        self.console = console_class(2, self.main, visible=False)
        self.console._statusHeight = lambda: 1
        self.console._fitToWorkArea = lambda: None
        self.console.parent_window = self.main
        self.console.opened = self.console.owner_active = self.console.auto_show_required = False
        self.console.saveState = lambda: self.events.append("console-save")
        self.console._scroll = lambda amount: self.events.append(("scroll", amount))
        self.main.console_window = self.console
        self.main.command = SimpleNamespace(
            ConsoleOpen=lambda: self.main.command_ConsoleOpen(None),
            ConsoleClose=lambda: self.main.command_ConsoleClose(None))
        self.main.activate()
        self.external = Base(3)
        self.dialog = Base(4, self.main)
        self.events.clear()

        # Exercise the real input handlers, including command execution and Esc priority.
        session_tree = ast.parse((ROOT / "clnch/clnch_inputsession.py").read_text(encoding="utf-8"))
        session = next(node for node in session_tree.body
                       if isinstance(node, ast.ClassDef) and node.name == "_CommandLineSession")
        self.namespace.update(self=self.main)
        exec(compile(ast.Module(body=[session], type_ignores=[]), "command-line", "exec"), self.namespace)  # noqa: S102  # Exercise the extracted session with the same fake windows.
        self.main.getStringWidth = len
        self.commandline = self.namespace["_CommandLineSession"](
            self.main, 1, "", escape_handler=lambda commandline: self.events.append("escape") or True)
        self.commandline.updateWindowWidth = lambda text: None
        handlers, _ = load_class("clnch_commandline.py", "_LauncherInputHandlers",
                                 {"__init__", "onKeyDown"}, self.namespace)
        self.commandline.keydown_handler = handlers(self.main).onKeyDown
        self.main.cmd_keymap = SimpleNamespace(table={(9, 0): self.main.command_ClearInput})
        self.main.keymap = SimpleNamespace(table={(121, 2): self.main.command_ConsoleToggle})
        self.continue_input = self.commandline._checkContinue

    def settle(self):
        self.main.onTimer()
        self.console.onTimerAutoShow()

    def test_owned_windows_without_console_and_external_exit(self):
        for clear in (True, False):
            with self.subTest(clear=clear):
                self.setUp()
                self.main.input_settings["CLEAR_ON_DEACTIVATE"] = clear
                self.main._onActivate(False)
                # The foreground still names the previous owner during WM_ACTIVATE.
                self.assertEqual(self.text, "draft")
                self.assertNotIn("write", self.events)
                self.dialog.activate()
                self.main.enabled = False
                nested = self.namespace["Base"](5, self.dialog)
                nested.activate()
                self.settle()
                self.assertTrue(self.main.isLauncherActive())
                self.assertEqual(self.text, "draft")
                self.assertNotIn("write", self.events)
                self.external.activate()
                self.settle()
                self.assertFalse(self.main.isLauncherActive())
                self.assertEqual(self.text, "" if clear else "draft")
                self.assertEqual(self.events.count("write"), 1)
                self.assertIn("console-save", self.events)
                self.settle()
                self.assertEqual(self.events.count("write"), 1)
                self.main.enabled = True
                self.main.hotkey_Activate()
                self.settle()
                self.assertTrue(self.main.isLauncherActive())
                self.assertEqual(self.text, "" if clear else "draft")

    def test_enabling_clear_in_owned_window_does_not_clear_input(self):
        self.main.input_settings["CLEAR_ON_DEACTIVATE"] = False
        self.dialog.activate()
        self.settle()
        self.main.input_settings["CLEAR_ON_DEACTIVATE"] = True
        self.main.saveState()
        self.settle()
        self.assertEqual(self.text, "draft")
        self.main.activate()
        self.settle()
        self.assertEqual(self.text, "draft")

    def test_empty_input_continues_in_owned_window_without_console(self):
        self.text = ""
        self.dialog.activate()
        self.settle()
        self.assertTrue(self.continue_input())
        self.external.activate()
        self.settle()
        self.assertFalse(self.continue_input())

    def set_text(self, text):
        self.text = text

    def open_console(self):
        self.main.command_ConsoleToggle(None)
        self.assertIs(self.foreground, self.console)
        self.assertEqual(self.focus, 2)
        self.assertTrue(self.console.opened)

    def test_unopened_console_keeps_deactivation_and_escape_behavior(self):
        for clear in (True, False):
            with self.subTest(clear=clear):
                self.main.activate()
                self.text = "draft"
                self.main.input_settings["CLEAR_ON_DEACTIVATE"] = clear
                self.external.activate()
                self.settle()
                self.assertEqual(self.text, "" if clear else "draft")
                self.assertEqual(self.continue_input(), not clear)
                self.settle()
                self.assertTrue(self.main.isVisible())
                self.assertFalse(self.console.isVisible())
        self.text = ""
        self.commandline._onKeyDown(27, 0)
        self.assertIn("escape", self.events)

    def test_open_focus_scroll_and_internal_moves_preserve_input(self):
        for text in ("", "draft"):
            with self.subTest(text=text):
                self.text = text
                self.open_console()
                self.assertEqual(self.text, text)
                self.assertTrue(self.continue_input())
                self.console._onKeyDown(38, 0)
                self.console._onKeyDown(33, 0)
                self.assertIn(("scroll", -1), self.events)
                self.assertIn(("scroll", -19), self.events)
                self.main.activate()
                self.settle()
                self.assertEqual(self.focus, 1)
                self.assertTrue(self.console.isVisible())
                self.assertEqual(self.text, text)
                self.assertNotIn("write", self.events)
                self.main.command_ConsoleClose(None)

    def test_control_f10_dispatch_does_not_end_input(self):
        self.commandline._onKeyDown(121, 2)
        self.assertIs(self.foreground, self.console)
        self.assertEqual(self.focus, 2)
        self.assertEqual(self.text, "draft")
        self.assertNotIn("quit", self.events)

    def test_hide_and_hotkey_restore_for_both_input_settings(self):
        for clear in (True, False):
            with self.subTest(clear=clear):
                self.setUp()
                self.main.input_settings["CLEAR_ON_DEACTIVATE"] = clear
                self.open_console()
                self.external.activate()
                self.settle()
                self.settle()
                self.assertFalse(self.main.isVisible())
                self.assertFalse(self.console.isVisible())
                self.assertTrue(self.console.opened)
                self.assertEqual(self.text, "" if clear else "draft")
                self.assertEqual(self.events.count("write"), 1)
                self.main.hotkey_Activate()
                self.settle()
                self.assertTrue(self.main.isVisible())
                self.assertTrue(self.console.isVisible())
                self.assertIs(self.foreground, self.main)
                self.assertEqual(self.focus, 1)

    def test_nonhide_modes_keep_both_visible_and_clear_only_on_external_move(self):
        for mode in ("clock", "empty"):
            with self.subTest(mode=mode):
                self.setUp()
                self.settings["MISC", "inactive_behavior"] = mode
                self.open_console()
                self.external.activate()
                self.settle()
                self.settle()
                self.assertEqual(self.text, "")
                self.assertTrue(self.main.isVisible())
                self.assertTrue(self.console.isVisible())
                self.settle()
                self.assertEqual(self.events.count("write"), 1)

    def test_owned_dialog_does_not_hide_windows_or_clear_input(self):
        self.open_console()
        self.dialog.activate()
        self.settle()
        self.assertTrue(self.main.isLauncherActive())
        self.assertTrue(self.main.isVisible())
        self.assertTrue(self.console.isVisible())
        self.assertEqual(self.text, "draft")
        self.assertNotIn("write", self.events)
        self.external.activate()
        self.settle()
        self.settle()
        self.assertFalse(self.console.isVisible())
        self.assertEqual(self.text, "")

    def test_explicit_close_returns_focus_and_does_not_reopen_on_hotkey(self):
        for close in (lambda c: c._onKeyDown(27, 0), lambda c: c._onKeyDown(121, 2),
                      lambda c: c._onClose(), lambda c: self.main.command_ConsoleClose(None)):
            with self.subTest(close=close):
                self.setUp()
                self.open_console()
                self.console.auto_show_required = True
                close(self.console)
                self.assertFalse(self.console.opened)
                self.assertFalse(self.console.isVisible())
                self.assertEqual(self.text, "draft")
                self.assertIs(self.foreground, self.main)
                self.assertEqual(self.focus, 1)
                self.external.activate()
                self.settle()
                self.main.hotkey_Activate()
                self.settle()
                self.assertFalse(self.console.isVisible())

    def test_main_escape_clears_then_explicitly_closes_console(self):
        self.open_console()
        self.main.activate()
        self.commandline._onKeyDown(27, 0)
        self.assertEqual(self.text, "")
        self.assertTrue(self.console.isVisible())
        self.commandline._onKeyDown(27, 0)
        self.assertFalse(self.console.opened)
        self.commandline._onKeyDown(27, 0)
        self.assertIn("escape", self.events)

    def test_input_clear_and_command_quit_keep_console_open(self):
        self.open_console()
        self.main.activate()
        self.commandline._onKeyDown(9, 0)
        self.assertEqual(self.text, "")
        self.assertIn("quit", self.events)
        self.assertTrue(self.console.isVisible())
        self.commandline.executeCommand(lambda info: None, None, None, quit=True)
        self.assertEqual(self.text, "")
        self.assertIn("quit", self.events)
        self.assertTrue(self.console.opened)
        self.assertTrue(self.console.isVisible())

    def test_auto_show_respects_hide_and_does_not_steal_focus(self):
        self.external.activate()
        self.settle()
        self.console.auto_show_required = True
        self.settle()
        self.assertTrue(self.console.opened)
        self.assertFalse(self.main.isVisible())
        self.assertFalse(self.console.isVisible())
        self.assertIs(self.foreground, self.external)
        self.main.hotkey_Activate()
        self.settle()
        self.assertTrue(self.console.isVisible())
        self.assertIs(self.foreground, self.main)

    def test_inactive_loop_and_top_level_treat_console_as_active(self):
        self.text = ""
        self.open_console()
        self.main.quit_requested = False
        self.main.activeMessageLoop = lambda: setattr(self.main, "quit_requested", True)
        self.main.topLevelMessageLoop()
        self.assertTrue(self.main.isVisible())
        self.external.activate()
        self.settle()
        checks = []
        def message_loop(check):
            checks.append(check())
            self.main.hotkey_Activate()
            checks.append(check())
        self.main.messageLoop = message_loop
        self.main.inactiveMessageLoop()
        self.assertEqual(checks, [True, False])


if __name__ == "__main__":
    unittest.main()
