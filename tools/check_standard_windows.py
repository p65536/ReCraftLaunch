"""Native standard-command checks on a private, noninteractive Windows station.

Run with Python315/tools/python.exe -B. The default uses no user clipboard,
settings or visible desktop. --interactive-foreground runs explicit foreground
or modal tests with temporary visible windows/settings and foreground restoration.
The foreground test replaces clipboard writes; modal tests do not write it. UAC consent and interactive IME composition remain manual.
--package DIR runs selected tests using its library.zip and native extensions.
"""
import configparser
import contextlib
import ctypes
import faulthandler
import importlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
import winreg
from contextlib import ExitStack, redirect_stderr
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from native_test_support import RUN_DIR

ROOT = Path(__file__).resolve().parent.parent

IPC_SENDER = '''import ctypes, sys
from ctypes import wintypes as w
u = ctypes.WinDLL("user32", use_last_error=True)
u.OpenWindowStationW.argtypes = (w.LPCWSTR, w.BOOL, w.DWORD)
u.OpenWindowStationW.restype = w.HANDLE
u.SetProcessWindowStation.argtypes = (w.HANDLE,)
station = u.OpenWindowStationW(sys.argv[1], False, 0x37f)
if not station or not u.SetProcessWindowStation(station):
    raise ctypes.WinError(ctypes.get_last_error())
u.OpenDesktopW.argtypes = (w.LPCWSTR, w.DWORD, w.BOOL, w.DWORD)
u.OpenDesktopW.restype = w.HANDLE
u.SetThreadDesktop.argtypes = (w.HANDLE,)
desktop = u.OpenDesktopW("StandardCommandTests", 0, False, 0x01ff)
if not desktop or not u.SetThreadDesktop(desktop):
    raise ctypes.WinError(ctypes.get_last_error())
class CopyData(ctypes.Structure):
    _fields_ = [("kind", ctypes.c_size_t), ("size", w.DWORD), ("data", w.LPVOID)]
payload = ctypes.create_string_buffer(sys.argv[3].encode("utf-8"))
packet = CopyData(0x101, len(payload.value), ctypes.cast(payload, w.LPVOID))
u.SendMessageTimeoutW.argtypes = (w.HWND, w.UINT, w.WPARAM, w.LPARAM,
    w.UINT, w.UINT, ctypes.POINTER(ctypes.c_size_t))
result = ctypes.c_size_t()
if not u.SendMessageTimeoutW(int(sys.argv[2]), 0x004a, 0, ctypes.addressof(packet), 2, 5000, ctypes.byref(result)):
    raise ctypes.WinError(ctypes.get_last_error())
'''

# The GUI child records both its startup mode and actual native window state.
PROBE = '''import ctypes, json, os, sys
from ctypes import wintypes as w
from pathlib import Path
class Startup(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("reserved", w.LPWSTR), ("desktop", w.LPWSTR),
        ("title", w.LPWSTR)] + [(n, w.DWORD) for n in
        ("x", "y", "cx", "cy", "charsx", "charsy", "fill", "flags")] + [
        ("show", w.WORD), ("reserved_count", w.WORD), ("reserved_bytes", w.LPVOID),
        ("stdin", w.HANDLE), ("stdout", w.HANDLE), ("stderr", w.HANDLE)]
startup = Startup(cb=ctypes.sizeof(Startup))
ctypes.windll.kernel32.GetStartupInfoW(ctypes.byref(startup))
u = ctypes.windll.user32
u.CreateWindowExW.argtypes = (w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID)
u.CreateWindowExW.restype = w.HWND
for name in ("ShowWindow", "IsIconic", "IsZoomed", "DestroyWindow"):
    getattr(u, name).argtypes = (w.HWND, ctypes.c_int) if name == "ShowWindow" else (w.HWND,)
hwnd = u.CreateWindowExW(0, "STATIC", "ReCraftLaunch test child", 0x00cf0000,
    0, 0, 300, 200, None, None, None, None)
if not hwnd:
    raise ctypes.WinError()
try:
    u.ShowWindow(hwnd, startup.show if startup.flags & 1 else 1)
    ctypes.windll.kernel32.GetCommandLineW.restype = w.LPWSTR
    result = {"command_line": ctypes.windll.kernel32.GetCommandLineW(), "args": sys.argv[2:], "cwd": os.getcwd(), "show": startup.show, "pid": os.getpid(),
        "minimized": bool(u.IsIconic(hwnd)), "maximized": bool(u.IsZoomed(hwnd))}
    output = Path(sys.argv[1])
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    temporary.replace(output)
finally:
    u.DestroyWindow(hwnd)
'''


def isolated_desktop(*, allow_create_access_denied=False):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.CreateWindowStationW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD,
                                           wintypes.DWORD, wintypes.LPVOID)
    user32.CreateWindowStationW.restype = wintypes.HANDLE
    user32.SetProcessWindowStation.argtypes = (wintypes.HANDLE,)
    user32.CreateDesktopW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPVOID,
                                    wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID)
    user32.CreateDesktopW.restype = wintypes.HANDLE
    user32.SetThreadDesktop.argtypes = (wintypes.HANDLE,)
    # Explicit station/desktop rights; GENERIC_ALL is denied on some hosts.
    station = user32.CreateWindowStationW(None, 0, 0x37F, None)
    if not station:
        error = ctypes.get_last_error()
        if allow_create_access_denied and error == 5:
            return None
        raise ctypes.WinError(error)
    if not user32.SetProcessWindowStation(station):
        raise ctypes.WinError(ctypes.get_last_error())
    desktop = user32.CreateDesktopW("StandardCommandTests", None, None, 0, 0x01FF, None)
    if not desktop or not user32.SetThreadDesktop(desktop):
        raise ctypes.WinError(ctypes.get_last_error())
    # Keep handles until process exit; never switch the user's input desktop.
    return user32, station, desktop


def main():
    faulthandler.dump_traceback_later(45, exit=True)
    package = None
    if "--package" in sys.argv:
        import native_test_support

        index = sys.argv.index("--package")
        package = Path(sys.argv[index + 1]).resolve()
        del sys.argv[index:index + 2]
        native_test_support.RUN_DIR = package
    interactive_foreground = "--interactive-foreground" in sys.argv
    if interactive_foreground:
        sys.argv.remove("--interactive-foreground")
        allowed = {"test_native_external_launch_and_utility_foreground",
                   "test_native_editor_modal_parent_states", "test_native_list_modal_parent_return",
                   "test_native_main_close_inactive_hide_and_reactivate",
                   "test_native_main_close_during_modal_keeps_child_and_recovers",
                   "test_native_owned_activation_and_external_exit"}
        if not sys.argv[1:] or not set(sys.argv[1:]) <= allowed:
            raise ValueError("Run only explicit foreground/modal tests on the interactive desktop")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetProcessWindowStation.restype = wintypes.HANDLE
        desktop_handles = (user32, user32.GetProcessWindowStation(), None)
    else:
        desktop_handles = isolated_desktop()
    user32 = desktop_handles[0]
    user32.GetUserObjectInformationW.argtypes = (wintypes.HANDLE, ctypes.c_int,
                                               wintypes.LPVOID, wintypes.DWORD,
                                               ctypes.POINTER(wintypes.DWORD))
    station_name = ctypes.create_unicode_buffer(256)
    needed = wintypes.DWORD()
    if not user32.GetUserObjectInformationW(desktop_handles[1], 2, station_name,
                                            ctypes.sizeof(station_name), ctypes.byref(needed)):
        raise ctypes.WinError(ctypes.get_last_error())
    sys.path[:0] = ([str(package / "library.zip"), str(package / "lib")] if package
                    else [str(ROOT), str(ROOT / "clnch"), str(RUN_DIR / "lib")])
    sys._clnch_app_dir = str(package or ROOT)
    import clnch_text

    import ckit

    clnch_text.initialize()
    ckit.registerWindowClass("ReCraftLaunchAuto" + str(os.getpid()))
    ckit.registerCommandInfoConstructor(ckit.CommandInfo)

    with tempfile.TemporaryDirectory(prefix="recraft-native-") as directory:
        data = Path(directory)
        ckit.setDataPath(directory)
        import clnch_cmdeditor
        import clnch_cmdlist
        import clnch_cmdstore
        import clnch_commandplatform
        import clnch_configmenu
        import clnch_ini
        import clnch_ipc
        import clnch_mainwindow
        import clnch_strings as strings

        if package:
            for module in (ckit, clnch_mainwindow, clnch_configmenu):
                assert str(package / "library.zip") in module.__file__, module.__file__
            for name in ("ckit.ckitcore", "pyauto.pyautocore", "clnch_native"):
                assert Path(sys.modules[name].__file__).parent == package / "lib"

        probe = data / "引数 probe.py"
        probe.write_text(PROBE, encoding="utf-8")
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        ckit.JobQueue.createDefaultQueue()

        class NativeCommandChecks(unittest.TestCase):
            def modal_openers(self):
                import clnch_fontlistwindow
                import clnch_listwindow
                import clnch_msgbox

                self.window.altenter_settings.update(action="application")
                return (
                    ("menu", lambda: clnch_listwindow.popMenu(self.window, 40, 16, items=["item"])),
                    ("hotkey", lambda: clnch_configmenu._configHotKeyAssign(self.window)),
                    ("sources", lambda: clnch_configmenu._configModifierSources(self.window)),
                    ("root", lambda: clnch_configmenu._editModifierRoot(self.window, "Root", "")),
                    ("altenter", lambda: clnch_configmenu._configAltEnterTarget(self.window)),
                    ("message", lambda: clnch_msgbox.popMessageBox(self.window, 0, "Test", "Message")),
                    ("editor", lambda: clnch_cmdeditor.open_editor(self.window)),
                    ("font", lambda: clnch_fontlistwindow.popFontMenu(self.window, ["MS Gothic"], 0)),
                    ("history", lambda: self.window.command_History(None)),
                    ("commands", lambda: clnch_cmdlist.open_list(self.window)),
                )

            def cancel_modal(self, child):
                if isinstance(child, clnch_cmdeditor.CommandEditor):
                    child._on_cancel()
                elif hasattr(child, "cancel"):
                    child.cancel()
                else:
                    child.onClose()

            def test_native_modal_failures_cleanup_and_reopen(self):
                import clnch_misc

                user32.IsWindow.argtypes = (wintypes.HWND,)
                init = ckit.TextWindow.__init__
                show = ckit.TextWindow.show
                destroy = ckit.TextWindow.destroy
                position = clnch_misc.adjustWindowPosition
                enable = self.window.enable
                activate = self.window.activate
                for name, opener in self.modal_openers():
                    for stage in ("position", "show", "disable", "loop", "result", "enable", "activate", "destroy", "multiple"):
                        with self.subTest(screen=name, stage=stage):
                            handles = []
                            failure = RuntimeError(stage)
                            def failed_result(failure=failure):
                                raise failure
                            def created(child, handles=handles, stage=stage, failed_result=failed_result, **kwargs):
                                init(child, **kwargs)
                                handles.append(child.getHWND())
                                if stage == "result":
                                    child.getResult = failed_result
                            def positioned(*args, stage=stage, failure=failure, **kwargs):
                                position(*args, **kwargs)
                                if stage == "position":
                                    raise failure
                            def shown(child, visible, *args, stage=stage, failure=failure):
                                show(child, visible, *args)
                                if visible and stage == "show":
                                    raise failure
                            def enabled(value, stage=stage, failure=failure):
                                enable(value)
                                if stage == ("enable" if value else "disable"):
                                    raise failure
                                if value and stage == "multiple":
                                    raise RuntimeError("enable cleanup")
                            def activated(stage=stage, failure=failure):
                                activate()
                                if stage == "activate":
                                    raise failure
                                if stage == "multiple":
                                    raise RuntimeError("activate cleanup")
                            def destroyed(child, stage=stage, failure=failure):
                                destroy(child)
                                if stage == "destroy":
                                    raise failure
                                if stage == "multiple":
                                    raise RuntimeError("destroy cleanup")
                            def loop(child, stage=stage, failure=failure, failed_result=failed_result):
                                self.assertFalse(self.window.isEnabled())
                                if stage in ("loop", "multiple"):
                                    raise failure
                                self.cancel_modal(child)
                                if stage == "result" and isinstance(child, clnch_cmdeditor.CommandEditor):
                                    child.result_saved = True
                                    original_draft = child.draft
                                    class FailedDraft:
                                        def __getattr__(self, key):
                                            if key == "name":
                                                return failed_result()
                                            return getattr(original_draft, key)
                                    child.draft = FailedDraft()
                            with (
                                patch.object(ckit.TextWindow, "__init__", created),
                                patch.object(ckit.TextWindow, "show", shown),
                                patch.object(ckit.TextWindow, "destroy", destroyed),
                                patch.object(ckit.TextWindow, "messageLoop", loop),
                                patch.object(clnch_misc, "adjustWindowPosition", positioned),
                                patch.object(self.window, "enable", enabled),
                                patch.object(self.window, "activate", activated),
                                self.assertRaises(RuntimeError) as caught,
                            ):
                                opener()
                            self.assertIs(caught.exception, failure)
                            self.assertTrue(self.window.isEnabled())
                            self.assertTrue(handles)
                            self.assertTrue(all(not user32.IsWindow(hwnd) for hwnd in handles))
                            if stage == "multiple":
                                self.assertEqual(len(failure.__notes__), 3)
                            # Reopen the same screen with native Enter/Esc handlers after failure.
                            with patch.object(ckit.TextWindow, "messageLoop", lambda child: self.cancel_modal(child)):
                                opener()
                            self.assertTrue(self.window.isEnabled())

            def test_native_modal_partial_constructors_release_owned_resources(self):
                import clnch_listwindow

                from ckit import ckitcore

                user32.IsWindow.argtypes = (wintypes.HWND,)
                init = ckit.TextWindow.__init__
                edit_init = ckit.EditWidget.__init__
                edit_destroy = ckit.EditWidget.destroy
                for name, opener in self.modal_openers():
                    with self.subTest(screen=name):
                        handles, edits, destroyed = [], [], []
                        def created(child, handles=handles, **kwargs):
                            init(child, **kwargs)
                            handles.append(child.getHWND())
                        def edit_created(edit, *args, edits=edits, **kwargs):
                            if edits:
                                raise RuntimeError("second edit")
                            edit_init(edit, *args, **kwargs)
                            edits.append(edit)
                        def edit_destroyed(edit, destroyed=destroyed):
                            edit_destroy(edit)
                            destroyed.append(edit)
                            raise RuntimeError("edit cleanup")
                        # All listed constructors either build edits or measure/layout text.
                        target = clnch_listwindow.ListWindow if name in ("menu", "sources", "history", "commands", "font") else ckit.TextWindow
                        with ExitStack() as stack:
                            stack.enter_context(patch.object(ckit.TextWindow, "__init__", created))
                            if name in ("editor", "altenter"):
                                stack.enter_context(patch.object(ckit.EditWidget, "__init__", edit_created))
                                stack.enter_context(patch.object(ckit.EditWidget, "destroy", edit_destroyed))
                                expected = "second edit"
                            else:
                                stack.enter_context(patch.object(target, "getStringWidth", side_effect=RuntimeError("layout")))
                                expected = "layout"
                            with self.assertRaisesRegex(RuntimeError, expected):
                                opener()
                        self.assertTrue(self.window.isEnabled())
                        # Root/AltEnter can fail while measuring the parent, before allocation.
                        self.assertTrue(all(not user32.IsWindow(hwnd) for hwnd in handles))
                        self.assertEqual(edits, destroyed)
                # Failure before the TextWindow text plane exists must still destroy HWND.
                handles = []
                original_plane = ckitcore.TextPlane
                def failed_plane(window, *args):
                    handles.append(window.getHWND())
                    raise RuntimeError("text plane")
                with patch.object(ckitcore, "TextPlane", failed_plane), self.assertRaisesRegex(RuntimeError, "text plane"):
                    ckit.TextWindow(show=False)
                self.assertTrue(all(not user32.IsWindow(hwnd) for hwnd in handles))
                self.assertIs(ckitcore.TextPlane, original_plane)

                # Row planes must be owned before their font setup can fail.
                handles, released = [], []
                def created_editor(child, **kwargs):
                    init(child, **kwargs)
                    handles.append(child.getHWND())
                class FailedRowPlane:
                    def __init__(self, *args):
                        self.native = original_plane(*args)
                    def setFont(self, font):
                        raise RuntimeError("row font")
                    def destroy(self):
                        self.native.destroy()
                        released.append(self)
                with (
                    patch.object(ckit.TextWindow, "__init__", created_editor),
                    patch.object(ckit, "TextPlane", FailedRowPlane),
                    self.assertRaisesRegex(RuntimeError, "row font"),
                ):
                    clnch_cmdeditor.CommandEditor(self.window)
                self.assertEqual(len(released), 1)
                self.assertTrue(all(not user32.IsWindow(hwnd) for hwnd in handles))

            def test_native_nested_editor_keeps_outer_parent_disabled(self):
                observations = []
                def loop(child):
                    self.assertFalse(self.window.isEnabled())
                    if isinstance(child, clnch_cmdeditor.CommandEditor):
                        self.key(ckit.VK_ESCAPE, window=child)
                with (
                    ExitStack() as cleanup,
                    ExitStack() as previous_cleanup,
                    patch.object(ckit.TextWindow, "messageLoop", loop),
                    clnch_cmdlist._show_list(self.window, [("Empty", "")], "", cleanup, previous_cleanup) as (child, action),
                ):
                    self.assertEqual(action["type"], "edit")
                    def shown():
                        observations.append(self.window.isEnabled())
                        self.assertFalse(child.isEnabled())
                    clnch_cmdeditor.open_editor(self.window, "", on_shown=shown, parent_window=child)
                    self.assertTrue(child.isEnabled())
                    self.assertFalse(self.window.isEnabled())
                    def failed_shown():
                        raise RuntimeError("nested callback")
                    with self.assertRaisesRegex(RuntimeError, "nested callback"):
                        clnch_cmdeditor.open_editor(self.window, on_shown=failed_shown, parent_window=child)
                    self.assertFalse(self.window.isEnabled())
                self.assertEqual(observations, [False])
                self.assertTrue(self.window.isEnabled())

            def test_native_already_disabled_modal_parent_stays_disabled(self):
                enable = self.window.enable
                for name, opener in self.modal_openers():
                    with self.subTest(screen=name):
                        enable(False)
                        try:
                            with (
                                patch.object(ckit.TextWindow, "messageLoop", lambda child: self.cancel_modal(child)),
                                patch.object(self.window, "activate") as activate,
                                patch.object(self.window, "foreground") as foreground,
                                patch.object(self.window, "enable", wraps=enable) as changes,
                            ):
                                opener()
                            self.assertFalse(self.window.isEnabled())
                            activate.assert_not_called()
                            if name == "history":
                                changes.assert_not_called()
                                foreground.assert_called_once_with()
                            else:
                                self.assertEqual([call.args for call in changes.call_args_list], [(False,)])
                        finally:
                            enable(True)

            def test_native_modal_key_callback_error_allows_cancel_and_reopen(self):
                import clnch_listwindow

                original = clnch_listwindow.ListWindow
                handles, errors = [], []
                def created(*args, **kwargs):
                    child = original(*args, **kwargs)
                    handles.append(child.getHWND())
                    def drive():
                        child.killTimer(drive)
                        try:
                            self.assertFalse(self.window.isEnabled())
                            if len(handles) == 1:
                                self.key(ckit.VK_F2, window=child)
                                self.assertFalse(self.window.isEnabled())
                                self.key(ckit.VK_ESCAPE, window=child)
                            else:
                                self.key(ckit.VK_RETURN, window=child)
                        except BaseException as error:  # noqa: BLE001  # Surface timer assertions and close the native modal loop.
                            errors.append(error)
                            child.quit()
                    child.setTimer(drive, 30)
                    return child
                def keydown(vk, mod):
                    if vk == ckit.VK_F2:
                        raise RuntimeError("modal key callback")
                    return False
                output = io.StringIO()
                with patch.object(clnch_listwindow, "ListWindow", created), redirect_stderr(output):
                    self.assertEqual(clnch_listwindow.popMenu(self.window, 40, 16, items=["item"], keydown_hook=keydown), -1)
                    self.assertEqual(clnch_listwindow.popMenu(self.window, 40, 16, items=["item"], keydown_hook=keydown), 0)
                self.assertIn("RuntimeError: modal key callback", output.getvalue())
                self.assertEqual(errors, [])
                self.assertTrue(self.window.isEnabled())
                user32.IsWindow.argtypes = (wintypes.HWND,)
                self.assertTrue(all(not user32.IsWindow(hwnd) for hwnd in handles))

            def setUp(self):
                read_state = patch.object(clnch_ini, "read_failed", False)
                read_state.start()
                self.addCleanup(read_state.stop)
                clnch_ini.ini = configparser.RawConfigParser()
                clnch_ini.ini_filename = str(data / "reclnch.ini")
                clnch_ini.set("INPUT", "history_mode", "off")
                (data / "commands.json").write_text("{}", encoding="utf-8")
                (data / "custom.py").write_text(
                    'def configure(window):\n'
                    '    window.custom_runs = getattr(window, "custom_runs", 0) + 1\n'
                    '    def custom(info):\n'
                    '        window.custom_args = list(info.args)\n'
                    '    window.launcher.command_list.append(("customonly", custom))\n',
                    encoding="utf-8")
                self.window = clnch_mainwindow.MainWindow()
                self.window.console_window.unregisterStdio()
                self.addCleanup(self.window.destroy)
                self.window.configure()
                self.ui = self.window.cmd_keymap["F12"].__self__

            def pump(self, condition, timeout=10):
                deadline = time.monotonic() + timeout
                self.window.messageLoop(lambda: not condition() and time.monotonic() < deadline)
                self.assertTrue(condition(), "Native event loop timed out")

            def apply(self, commands):
                (data / "commands.json").write_text(json.dumps(commands), encoding="utf-8")
                self.ui.reload_commands()

            def test_native_main_alt_f4_keeps_input(self):
                def press():
                    edit = self.window.commandline_edit
                    self.key(ckit.VK_F4, ckit.MODKEY_ALT, system=True)
                    self.assertIs(self.window.commandline_edit, edit)
                    self.assertEqual(edit.getText(), "draft")
                    self.assertFalse(self.window.quit_requested)
                self.input_action("draft", press)

            def test_native_main_close_restarts_input_without_quitting(self):
                window = self.window
                window.active = True
                window.commandline_history = ["history sentinel"]
                entered, errors = [], []
                original = window.activeMessageLoop
                def active():
                    entered.append(True)
                    original("draft" if len(entered) == 1 else "")
                def drive():
                    try:
                        self.assertFalse(window.quit_requested)
                        self.assertIsNotNone(window.commandline_edit)
                        if len(entered) == 1:
                            self.assertEqual(window.commandline_edit.getText(), "draft")
                            # SC_CLOSE is the system-menu/Alt+F4 close request.
                            user32.SendMessageW(window.getHWND(), 0x0112, 0xf060, 0)
                        else:
                            self.assertEqual(window.commandline_edit.getText(), "")
                            self.key(ord("A"))
                            user32.SendMessageW(window.getHWND(), 0x0102, ord("a"), 0)
                            self.assertEqual(window.commandline_edit.getText(), "a")
                            window.command_Quit(None)
                    except BaseException as error:  # noqa: BLE001  # Propagate timer assertions after leaving the native loop.
                        errors.append(error)
                        window.command_Quit(None)
                user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
                window.setTimer(drive, 30)
                try:
                    with patch.object(window, "activeMessageLoop", side_effect=active):
                        window.topLevelMessageLoop()
                finally:
                    window.killTimer(drive)
                self.assertEqual(errors, [])
                self.assertEqual(len(entered), 2)
                self.assertTrue(window.quit_requested)
                self.assertIsNone(window.commandline_edit)
                self.assertIsNone(window.keydown_hook)
                self.assertEqual(window.commandline_history, ["history sentinel"])

            def test_native_main_close_inactive_hide_and_reactivate(self):
                window = self.window
                if interactive_foreground:
                    user32.GetForegroundWindow.restype = wintypes.HWND
                    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
                    previous = user32.GetForegroundWindow()
                    self.addCleanup(user32.SetForegroundWindow, previous)
                clnch_ini.set("MISC", "inactive_behavior", "hide")
                window.inactivate()
                window.active = False
                def close():
                    window.killTimer(close)
                    user32.PostMessageW(window.getHWND(), 0x0010, 0, 0)
                user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
                for _ in range(2):
                    window.setTimer(close, 30)
                    window.inactiveMessageLoop()
                    self.assertFalse(window.quit_requested)
                    self.assertFalse(window.isVisible())
                window.hotkey_Activate()
                # IsWindowVisible/activation are unavailable on a private station.
                user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
                self.assertTrue(user32.GetWindowLongW(window.getHWND(), -16) & 0x10000000)
                self.assertTrue(window.isEnabled())
                if interactive_foreground:
                    self.assertTrue(window.isVisible())
                    user32.GetActiveWindow.restype = wintypes.HWND
                    user32.GetFocus.restype = wintypes.HWND
                    self.pump(lambda: window.active)
                    self.assertEqual(user32.GetActiveWindow(), window.getHWND())
                    self.assertEqual(user32.GetFocus(), window.getHWND())
                self.input_action("resumed", lambda: self.assertEqual(window.commandline_edit.getText(), "resumed"))

            def test_native_main_close_during_modal_keeps_child_and_recovers(self):
                self.modal_desktop_state()
                window = self.window
                user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
                handles, ticks, errors = [], [], []
                def heartbeat():
                    ticks.append(True)
                def close(editor):
                    handles.append(editor.getHWND())
                    self.assertFalse(window.isEnabled())
                    user32.SendMessageW(window.getHWND(), 0x0010, 0, 0)
                    self.assertFalse(window.quit_requested)
                    self.assertFalse(window.isEnabled())
                    window.command_Quit(None)
                    self.assertFalse(window.quit_requested)
                    self.assertTrue(editor.isEnabled())
                    self.assert_modal_parent(editor, window, True)
                    def finish():
                        editor.killTimer(finish)
                        window.killTimer(heartbeat)
                        try:
                            self.assertTrue(ticks, "Main timers must keep running while the modal child stays open")
                        except BaseException as error:  # noqa: BLE001  # Report timer failures after closing the modal loop.
                            errors.append(error)
                        user32.SendMessageW(editor.getHWND(), 0x0010, 0, 0)
                    window.setTimer(heartbeat, 10)
                    editor.setTimer(finish, 90)
                try:
                    self.assertIsNone(self.run_editor(close))
                finally:
                    window.killTimer(heartbeat)
                self.assertEqual(errors, [])
                self.assertFalse(user32.IsWindow(handles[0]))
                self.assertTrue(window.isEnabled())
                if interactive_foreground:
                    self.assertEqual(user32.GetActiveWindow(), window.getHWND())
                    self.assertEqual(user32.GetFocus(), window.getHWND())
                self.input_action("resumed", lambda: self.assertEqual(window.commandline_edit.getText(), "resumed"))
                self.assertFalse(window.quit_requested)

            def test_native_endsession_save_and_explicit_quit_cleanup(self):
                window = self.window
                user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
                with (patch.object(window, "saveState", wraps=window.saveState) as save,
                      patch.object(clnch_ini, "write", wraps=clnch_ini.write) as write):
                    user32.SendMessageW(window.getHWND(), 0x0016, 0, 0)
                    save.assert_not_called()
                    write.assert_not_called()
                    user32.SendMessageW(window.getHWND(), 0x0016, 1, 0)
                    save.assert_called_once_with()
                    write.assert_called_once_with()
                self.assertFalse(window.quit_requested)
                self.input_action("quit", lambda: self.key(ckit.VK_RETURN))
                self.assertTrue(window.quit_requested)
                window.stop()
                window.saveState()
                clnch_ini.write()
                saved = configparser.RawConfigParser()
                saved.read(clnch_ini.ini_filename, encoding="utf-8")
                self.assertTrue(saved.has_section("GEOMETRY"))
                cleaned = []
                window.registerConfigCleanup(lambda: cleaned.append(True))
                hwnd, console = window.getHWND(), window.console_window.getHWND()
                self.doCleanups()
                self.assertEqual(cleaned, [True])
                self.assertFalse(user32.IsWindow(hwnd))
                self.assertFalse(user32.IsWindow(console))

            def test_native_popmenu_optional_limits_and_cleanup(self):
                import clnch_listwindow
                original = clnch_listwindow.ListWindow
                handles, errors = [], []
                user32.IsWindow.argtypes = (wintypes.HWND,)
                for max_width, max_height in ((None, None), (20, None), (None, 6), (20, 6)):
                    for items in ([], [""], ["long Japanese 日本語 " * 30] * 8):
                        for status in (None, lambda width, select: "status " * 20):
                            for return_modkey in (False, True):
                                with self.subTest(width=max_width, height=max_height, items=len(items),
                                                  status=bool(status), modifiers=return_modkey):
                                    def created(*args, max_width=max_width, max_height=max_height, status=status, **kwargs):
                                        child = original(*args, **kwargs)
                                        handles.append(child.getHWND())
                                        self.addCleanup(lambda child=child, hwnd=handles[-1]: child.destroy() if user32.IsWindow(hwnd) else None)
                                        limit_width, limit_height = child._size_limits
                                        padding = (round(clnch_listwindow.HORIZONTAL_PADDING * child.getDisplayScaling()) * 2 + child.getCharSize()[0] - 1) // child.getCharSize()[0]
                                        self.assertLessEqual(child.width(), limit_width - padding)
                                        self.assertLessEqual(child.height(), limit_height)
                                        if max_width is not None:
                                            self.assertLessEqual(child.width(), max_width - padding)
                                        if max_height is not None:
                                            self.assertLessEqual(child.height(), max(max_height, child.item_height + child.status_rows))
                                        self.assertEqual(bool(child.status_rows), bool(status))
                                        def drive():
                                            child.killTimer(drive)
                                            try:
                                                self.assertFalse(self.window.isEnabled())
                                                self.key(ckit.VK_ESCAPE, window=child)
                                            except BaseException as error:  # noqa: BLE001  # Surface callback assertions and terminate the modal test.
                                                errors.append(error)
                                                child.quit()
                                        child.setTimer(drive, 10)
                                        return child
                                    with patch.object(clnch_listwindow, "ListWindow", created):
                                        result = clnch_listwindow.popMenu(self.window, max_width, max_height,
                                            items=items, statusbar_handler=status, return_modkey=return_modkey)
                                    self.assertEqual(result, (-1, 0) if return_modkey else -1)
                                    self.assertTrue(self.window.isEnabled())
                self.assertEqual(errors, [])
                user32.IsWindow.argtypes = (wintypes.HWND,)
                self.assertTrue(all(not user32.IsWindow(hwnd) for hwnd in handles))

            def test_native_widget_timer_ime_and_move(self):
                import gc
                import weakref

                bar = ckit.ProgressBarWidget(self.window, 1, 1, 20, 1)
                bar.setValue([0.5])
                for _ in range(3):
                    bar.setValue(None)
                    bar.setValue(None)
                    self.pump(lambda bar=bar: bar.busy_anim_theta > 0, timeout=2)
                    bar.setValue([0.5])
                    phase = (bar.busy_anim_theta, bar.busy_anim_chase)
                    done = []
                    self.window.delayedCall(lambda done=done: done.append(True), 110)
                    self.pump(lambda done=done: bool(done), timeout=2)
                    self.assertEqual((bar.busy_anim_theta, bar.busy_anim_chase), phase)
                bar.setValue(None)
                bar.show(False)
                phase = bar.busy_anim_theta
                done = []
                self.window.delayedCall(lambda done=done: done.append(True), 110)
                self.pump(lambda done=done: bool(done), timeout=2)
                self.assertEqual(bar.busy_anim_theta, phase)
                bar.show(True)
                bar.show(True)
                self.pump(lambda bar=bar: bar.busy_anim_theta != phase, timeout=2)
                bar.destroy()
                bar.destroy()
                bar.setValue(None)
                bar.show(True)
                reference = weakref.ref(bar)
                del bar
                gc.collect()
                self.assertIsNone(reference(), "Native timer retained a destroyed widget")
                widget = ckit.TimeWidget(self.window, 1, 2, (2024, 2, 29, 12, 34, 56))
                self.addCleanup(widget.destroy)
                widget.enableCursor(True)
                widget.onKeyDown(ckit.VK_RIGHT, 0)
                fields = [widget.year_edit, widget.month_edit, widget.day_edit, widget.hour_edit,
                          widget.minute_edit, widget.second_edit]
                with patch.object(self.window, "enableIme", wraps=self.window.enableIme) as ime, \
                     patch.object(self.window, "setImeRect", wraps=self.window.setImeRect) as rectangle:
                    fields[1].enableIme(True)
                    fields[1].enableIme(False)
                    self.assertEqual([call.args for call in ime.call_args_list], [(True,), (False,)])
                    fields[0].enableIme(True)
                    self.assertEqual(ime.call_count, 2)
                    fields[1].enableIme(True)
                    widget.setPosSize(3, 4, 80, 10)
                    rectangle.assert_called_with((*self.window.charToClient(9, 4), *self.window.charToClient(11, 5)))
                self.assertEqual([(edit.x, edit.y) for edit in fields],
                                 [(4, 4), (9, 4), (12, 4), (16, 4), (19, 4), (22, 4)])
                self.assertEqual(widget.focus, widget.FOCUS_MONTH)
                self.assertTrue(fields[1].enable_cursor)
                widget.show(False)
                self.assertTrue(all(not edit.visible for edit in fields))
                widget.show(True)
                widget.paint()
                self.assertEqual(widget.getValue(), (2024, 2, 29, 12, 34, 56))
                widget.month_edit.setText("02")
                widget.day_edit.setText("30")
                with self.assertRaises(ValueError):
                    widget.getValue()
                widget.day_edit.setText("29")
                self.assertEqual(widget.getValue(), (2024, 2, 29, 12, 34, 56))
                # Reuse this process's private desktop when loading the pixel-buffer helper.
                with patch("check_standard_windows.isolated_desktop", return_value=desktop_handles):
                    import test_window_show as window_show
                host = ckit.TextWindow(x=0, y=0, width=30, height=10, show=False, parent_window=self.window,
                                       bg_color=(17, 34, 51))
                self.addCleanup(host.destroy)
                color = ckit.ColorWidget(host, 0, 1, 20, 1, "color", (1, 2, 3))
                self.addCleanup(color.destroy)
                planes = [color.frame_plane, color.color_plane]
                host.show(True, False)
                buffer = window_show.WindowShowTests.buffer(self, host)
                px, py = color.color_plane.getPosition()
                def pixel():
                    host.flushPaint()
                    return window_show.gdi32.GetPixel(buffer.dc, px + 2, py + 2)
                self.assertEqual(pixel(), 1 | 2 << 8 | 3 << 16)
                color.show(False)
                self.assertEqual(pixel(), 17 | 34 << 8 | 51 << 16)
                color.show(True)
                self.assertEqual(pixel(), 1 | 2 << 8 | 3 << 16)
                color.destroy()
                color.destroy()
                for plane in planes:
                    with self.assertRaises(ValueError):
                        plane.getPosition()
                candidates = []
                for edit in fields:
                    edit.list_window = edit.createCandidateWindow()
                    candidates.append(edit.list_window.getHWND())
                widget.destroy()
                widget.destroy()
                user32.IsWindow.argtypes = (wintypes.HWND,)
                self.assertTrue(all(not user32.IsWindow(hwnd) for hwnd in candidates))

            def test_native_input_status_width_matches_paint_and_resize(self):
                import clnch_inputsession

                clnch_ini.set("GEOMETRY", "min_width", "18")
                clnch_ini.set("GEOMETRY", "max_width", "40")
                window = self.window
                original_init = ckit.EditWidget.__init__
                for status in ("", "OK", "状態"):
                    for text in ("", "入力" * 5, "x" * 80):
                        with self.subTest(status=status, text=text):
                            initial = []
                            current_status = [status]
                            session = clnch_inputsession._CommandLineSession(
                                window, clnch_mainwindow.PAINT_STATUS_BAR, "題", text,
                                status_handler=lambda info, current_status=current_status: current_status[0])
                            def create(edit, *args, initial=initial, **kwargs):
                                initial.append(args[3])
                                original_init(edit, *args, **kwargs)
                            def check_layout(text, status, session=session):
                                status_width = window.getStringWidth(status) + 3 if status else 0
                                expected = min(40, max(18, session.title_width + window.getStringWidth(text) + 2 + status_width))
                                self.assertEqual(window.width(), expected)
                                edit_width = expected - session.title_width - status_width
                                self.assertEqual(session.getEditWidthFromWindowWidth(expected), edit_width)
                                with patch.object(window, "putString", wraps=window.putString) as put:
                                    session._onPaint(0, 0, expected, 1)
                                self.assertEqual(window.commandline_edit.width, edit_width)
                                self.assertEqual(put.call_args_list[1].args[:4], (expected - status_width, 0, status_width, 1))
                                self.assertEqual(put.call_args_list[1].args[5], "  " + status + " " if status else "")
                                with patch.object(window, "active", False), \
                                     patch.object(window, "putString", wraps=window.putString) as put:
                                    session._onPaint(0, 0, expected, 1)
                                self.assertEqual(put.call_args_list[1].args[5], " " * status_width)
                                self.assertEqual(window.commandline_edit.width, edit_width)
                                window.flushPaint()
                                return edit_width
                            def drive(check, initial=initial, check_layout=check_layout, text=text,
                                      status=status, current_status=current_status, session=session):
                                self.assertEqual(initial, [check_layout(text, status)])
                                for updated_text, updated_status in (("自動拡幅" * 20, "更新"), ("", ""), ("短文", "OK")):
                                    current_status[0] = updated_status
                                    window.commandline_edit.setText(updated_text)
                                    session._onUpdate(ckit.EditWidget.UpdateInfo(updated_text, [len(updated_text)] * 2))
                                    check_layout(updated_text, updated_status)
                            with patch.object(ckit.EditWidget, "__init__", create), \
                                 patch.object(window, "messageLoop", side_effect=drive):
                                session.run()

            def test_native_time_arrows_select_destination_and_keep_endpoints(self):
                timestamp = (2024, 2, 29, 12, 34, 56)
                widget = ckit.TimeWidget(self.window, 0, 0, timestamp)
                self.addCleanup(widget.destroy)
                fields = [widget.year_edit, widget.month_edit, widget.day_edit,
                          widget.hour_edit, widget.minute_edit, widget.second_edit]
                widget.enableCursor(True)
                for vk, step in ((ckit.VK_LEFT, -1), (ckit.VK_RIGHT, 1)):
                    for source in range(6):
                        with self.subTest(vk=vk, source=source):
                            for edit in fields:
                                edit.setSelection([1, 1])
                            widget.focus = source
                            widget.paint()
                            destination = min(5, max(0, source + step))
                            self.assertIsNone(widget.onKeyDown(vk, 0))
                            self.assertEqual(widget.focus, destination)
                            for index, edit in enumerate(fields):
                                selected = index == destination and destination != source
                                self.assertEqual(edit.getSelection(), [0, len(edit.getText())] if selected else [1, 1])
                                self.assertEqual(edit.enable_cursor, index == destination)
                            self.assertEqual(widget.getValue(), timestamp)
                            self.window.flushPaint()

            def test_native_color_label_width_stays_inside_allocation(self):
                host = ckit.TextWindow(x=0, y=0, width=40, height=3, show=False, parent_window=self.window)
                self.addCleanup(host.destroy)
                color = ckit.ColorWidget(host, 2, 1, 20, 1, "long label 日本語" * 4, (1, 2, 3))
                self.addCleanup(color.destroy)
                with patch("check_standard_windows.isolated_desktop", return_value=desktop_handles):
                    import test_window_show as window_show
                host.show(True, False)
                buffer = window_show.WindowShowTests.buffer(self, host)
                for width in (0, 1, 2, 3, 4, 5, 6, 7, 20):
                    for focused in (False, True):
                        with self.subTest(width=width, focused=focused):
                            color.setPosSize(2, 1, width, 1)
                            color.enableCursor(focused)
                            right = color.x + width
                            # The existing four-cell swatch is outside this label-only fix.
                            if width >= 4:
                                host.putString(right, 1, 2, 1, ckit.Attribute(fg=(17, 34, 51), bg=(17, 34, 51)), "  ")
                                host.flushPaint()
                                left, top = host.charToClient(right, 1)
                                end, bottom = host.charToClient(right + 2, 2)
                                before = [window_show.gdi32.GetPixel(buffer.dc, x, y)
                                          for y in range(top, bottom) for x in range(left, end)]
                            with patch.object(host, "putString", wraps=host.putString) as put:
                                color.paint()
                            self.assertEqual(put.call_args.args[:4], (7, 1, max(0, width - 5), 1))
                            if put.call_args.args[2]:
                                self.assertLessEqual(put.call_args.args[0] + put.call_args.args[2], color.x + width)
                            host.flushPaint()
                            if width >= 4:
                                self.assertEqual([window_show.gdi32.GetPixel(buffer.dc, x, y)
                                                  for y in range(top, bottom) for x in range(left, end)], before)

            def test_native_widget_partial_construction_cleanup(self):
                from ckit import ckit_widget
                for fail_at in (0, 1, 2):
                    planes = []
                    original = ckit_widget.ckitcore.ImagePlane
                    def create(*args, planes=planes, fail_at=fail_at, original=original, **kwargs):
                        if len(planes) == fail_at:
                            raise RuntimeError("plane creation")
                        plane = original(*args, **kwargs)
                        planes.append(plane)
                        return plane
                    with patch.object(ckit_widget.ckitcore, "ImagePlane", create), \
                         patch.object(ckit.ColorWidget, "paint", side_effect=RuntimeError("paint")), \
                         self.assertRaises(RuntimeError):
                        ckit.ColorWidget(self.window, 0, 0, 20, 1, "color", (1, 2, 3))
                    for plane in planes:
                        with self.assertRaises(ValueError):
                            plane.getPosition()
                user32.IsWindow.argtypes = (wintypes.HWND,)
                for fail_at in range(7):
                    handles = []
                    original = ckit_widget.EditWidget
                    class FailingEdit(original):
                        def __init__(edit, *args, handles=handles, fail_at=fail_at, original=original, **kwargs):
                            if len(handles) == fail_at:
                                raise RuntimeError("edit creation")
                            original.__init__(edit, *args, **kwargs)
                            edit.list_window = edit.createCandidateWindow()
                            handles.append(edit.list_window.getHWND())
                    with patch.object(ckit_widget, "EditWidget", FailingEdit), \
                         patch.object(ckit.TimeWidget, "paint", side_effect=RuntimeError("paint")), \
                         self.assertRaises(RuntimeError):
                        ckit.TimeWidget(self.window, 0, 0, (2024, 2, 29, 0, 0, 0))
                    self.assertTrue(all(not user32.IsWindow(hwnd) for hwnd in handles))

            def test_native_synccall_timer_exception_and_network_notification(self):
                owner = threading.get_ident()
                done = threading.Event()
                outcome = {}
                failure = KeyboardInterrupt("SyncCall callback")
                calls = []
                resource = r"\\recraft-test\share"

                def fail():
                    calls.append(threading.get_ident())
                    raise failure

                def connect(hwnd, remote):
                    calls.append(threading.get_ident())
                    self.assertEqual((hwnd, remote), (self.window.getHWND(), resource))
                    raise OSError("connection test failure")

                def run():
                    try:
                        try:
                            self.window.synccall(fail)
                        except KeyboardInterrupt as error:
                            outcome["callback_error"] = error
                        outcome["network_result"] = self.window._onCheckNetConnection(resource)
                        outcome["result"] = self.window.synccall(lambda: (threading.get_ident(), "next"))
                    except BaseException as error:  # noqa: BLE001  # Report worker failures instead of losing them in a thread.
                        outcome["error"] = error
                    finally:
                        done.set()

                output = io.StringIO()
                thread = threading.Thread(target=run, daemon=True)
                with (patch.object(clnch_mainwindow.clnch_native, "addConnection", side_effect=connect) as connection,
                      patch("sys.stdout", output)):
                    thread.start()
                    try:
                        self.pump(done.is_set, timeout=5)
                    finally:
                        thread.join(3)
                self.assertFalse(thread.is_alive(), "SyncCall worker did not finish")
                self.assertEqual(outcome, {"callback_error": failure, "network_result": None,
                                           "result": (owner, "next")})
                self.assertEqual(calls, [owner, owner])
                connection.assert_called_once_with(self.window.getHWND(), resource)
                self.assertIn(strings.CONNECT_ERROR.format(resource=resource), output.getvalue())
                self.assertIn("connection test failure", output.getvalue())

            def invoke(self, name, args=(), mod=0):
                handler = next(handler for key, handler in self.window.launcher.command_list
                               if key.lower() == name.lower())
                handler(SimpleNamespace(args=list(args), mod=mod))

            def key(self, vk, mod=0, window=None, *, system=False):
                user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
                user32.GetKeyboardState.argtypes = (ctypes.POINTER(ctypes.c_ubyte),)
                user32.SetKeyboardState.argtypes = (ctypes.POINTER(ctypes.c_ubyte),)
                original = (ctypes.c_ubyte * 256)()
                self.assertTrue(user32.GetKeyboardState(original))
                keys = (ctypes.c_ubyte * 256)()
                for bit, code in ((1, ckit.VK_MENU), (2, ckit.VK_CONTROL), (4, ckit.VK_SHIFT)):
                    keys[code] = 0x80 if mod & bit else 0
                self.assertTrue(user32.SetKeyboardState(keys))
                try:
                    user32.SendMessageW((window or self.window).getHWND(),
                        0x0104 if system else 0x0100, vk, 1 | (1 << 29 if system else 0))
                finally:
                    self.assertTrue(user32.SetKeyboardState(original))

            def input_action(self, text, action):
                errors = []
                def drive():
                    self.window.killTimer(drive)
                    try:
                        action()
                    except BaseException as error:  # noqa: BLE001  # Surface timer failures to the test and leave the native loop.
                        errors.append(error)
                    finally:
                        self.window.quit()
                self.window.setTimer(drive, 30)
                self.window.activeMessageLoop(text)
                self.assertEqual(errors, [])
                self.assertIsNone(self.window.commandline_edit)
                self.assertIsNone(self.window.keydown_hook)

            def test_native_documented_ckit(self):
                from test_extension_examples import example_sources

                sources = example_sources()
                scripts = data / "scripts"
                scripts.mkdir(exist_ok=True)
                (scripts / "my_planes.py").write_text(sources["planes_module"], encoding="utf-8")
                (data / "custom.py").write_text(sources["planes_setup"], encoding="utf-8")
                user32.IsWindow.argtypes = (wintypes.HWND,)
                user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
                window_type, text_type, image_type = ckit.Window, ckit.TextPlane, ckit.ImagePlane
                class FailingLoopWindow(window_type):
                    def messageLoop(self):
                        raise RuntimeError("loop")
                with patch.object(sys, "path", [str(scripts), *sys.path]), patch.dict(sys.modules):
                    importlib.invalidate_caches()
                    sys.modules.pop("my_planes", None)
                    self.window.configure()
                    for mode in ("escape", "close", "disabled", "plane_failure", "loop_failure"):
                        with self.subTest(mode=mode):
                            created, texts, images, errors = [], [], [], []
                            self.window.enable(mode != "disabled")
                            def create(*args, mode=mode, created=created, texts=texts, images=images,
                                       errors=errors, **kwargs):
                                constructor = FailingLoopWindow if mode == "loop_failure" else window_type
                                child = constructor(*args, **kwargs)
                                created.append((child, child.getHWND()))
                                def drive():
                                    try:
                                        self.assertFalse(self.window.isEnabled())
                                        self.assertEqual(texts[0].getPosition(), (8, 8))
                                        self.assertEqual(texts[0].getSize(), (304, 24))
                                        self.assertGreater(texts[0].getCharSize()[0], 0)
                                        self.assertEqual(images[0].getImage().getSize(), (2, 1))
                                        self.assertEqual(images[0].getSize(), (64, 32))
                                        child.flushPaint()
                                        message = 0x0010 if mode == "close" else 0x0100
                                        self.assertTrue(user32.PostMessageW(child.getHWND(), message, ckit.VK_ESCAPE, 0))
                                    except BaseException as error:  # noqa: BLE001  # Surface native callback assertions outside the loop.
                                        errors.append(error)
                                        child.quit()
                                child.delayedCall(drive, 20)
                                return child
                            def text_plane(*args, mode=mode, texts=texts, **kwargs):
                                if mode == "plane_failure":
                                    raise RuntimeError("plane construction")
                                plane = text_type(*args, **kwargs)
                                texts.append(plane)
                                return plane
                            def image_plane(*args, images=images, **kwargs):
                                plane = image_type(*args, **kwargs)
                                images.append(plane)
                                return plane
                            with (patch.object(ckit, "Window", side_effect=create),
                                  patch.object(ckit, "TextPlane", side_effect=text_plane),
                                  patch.object(ckit, "ImagePlane", side_effect=image_plane)):
                                if mode == "loop_failure":
                                    with self.assertRaisesRegex(RuntimeError, "loop"):
                                        self.invoke("mypreview")
                                elif mode == "plane_failure":
                                    with self.assertRaisesRegex(RuntimeError, "plane construction"):
                                        self.invoke("mypreview")
                                else:
                                    self.invoke("mypreview")
                            self.assertEqual(errors, [])
                            child, hwnd = created[0]
                            self.assertFalse(user32.IsWindow(hwnd))
                            with self.assertRaises(ValueError):
                                child.getHWND()
                            for plane in [*texts, *images]:
                                with self.assertRaises(ValueError):
                                    plane.getSize()
                            self.assertEqual(self.window.isEnabled(), mode != "disabled")
                    self.window.enable(True)

            def test_native_documented_clnch_native(self):
                from test_extension_examples import example_sources

                sources = example_sources()
                scripts = data / "scripts"
                scripts.mkdir(exist_ok=True)
                (scripts / "my_files.py").write_text(sources["files_module"], encoding="utf-8")
                (data / "custom.py").write_text(sources["files_setup"], encoding="utf-8")
                folder = data / "native-doc-files"
                folder.mkdir()
                sample = folder / "sample.txt"
                sample.write_bytes(b"abc")
                with patch.object(sys, "path", [str(scripts), *sys.path]), patch.dict(sys.modules):
                    importlib.invalidate_caches()
                    sys.modules.pop("my_files", None)
                    self.window.configure()
                    native = sys.modules["my_files"].clnch_native
                    for args, expected in (([], "Usage:"), ([str(folder / "*")], "Entries: 1"),
                                           ([str(folder / "*.absent")], "Entries: 0")):
                        output = io.StringIO()
                        with contextlib.redirect_stdout(output):
                            self.invoke("mystat", args)
                        self.assertIn(expected, output.getvalue())
                        if expected == "Entries: 1":
                            self.assertIn("sample.txt 3 (", output.getvalue())
                    with self.assertRaises(OSError):
                        self.invoke("mystat", [str(folder / "missing" / "*")])
                    first = native.findFile(str(folder / "*"))
                    sample.write_bytes(b"abcdef")
                    self.assertEqual(native.findFile(str(folder / "*"), use_cache=True), first)
                    refreshed = native.findFile(str(folder / "*"), use_cache=False)
                    self.assertEqual(refreshed[0][1], 6)
                    self.assertEqual(len(refreshed[0][2]), 6)
                    self.assertEqual(sample.read_bytes(), b"abcdef")
                    self.assertIsNone(self.window.keydown_hook)

            def test_native_documented_pyauto(self):
                from test_extension_examples import example_sources

                sources = example_sources()
                scripts = data / "scripts"
                scripts.mkdir(exist_ok=True)
                (scripts / "my_native.py").write_text(sources["native_module"], encoding="utf-8")
                (data / "custom.py").write_text(sources["native_setup"], encoding="utf-8")
                output = io.StringIO()
                with (patch.object(sys, "path", [str(scripts), *sys.path]), patch.dict(sys.modules),
                      contextlib.redirect_stdout(output)):
                    importlib.invalidate_caches()
                    sys.modules.pop("my_native", None)
                    self.window.configure()
                    self.invoke("mynative")
                    native = sys.modules["my_native"].pyauto
                user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
                title = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(self.window.getHWND(), title, len(title))
                self.assertIn("Title: " + title.value, output.getvalue())
                self.assertIn("Pixel match: (1, 0)", output.getvalue())
                self.assertIn("Prepared events: 2", output.getvalue())
                target = native.Window.fromHWND(self.window.getHWND())
                self.assertIs(native.Window.fromHWND(target.getHWND()), target)
                self.assertIs(native.Window.find(target.getClassName(), target.getText()), target)
                self.assertIsNone(native.Window.fromHWND(0))
                self.assertEqual(target.getRect(), self.window.getWindowRect())
                seen = []
                native.Window.enum(lambda window, arg: arg.append(window) or 0, seen)
                self.assertEqual(len(seen), 1)


            def test_native_documented_textwidget(self):
                from test_extension_examples import example_sources

                sources = example_sources()
                scripts = data / "scripts"
                scripts.mkdir(exist_ok=True)
                (scripts / "my_text.py").write_text(sources["textwidget_module"], encoding="utf-8")
                (data / "custom.py").write_text(sources["textwidget_setup"], encoding="utf-8")
                output, errors, created = io.StringIO(), [], []
                with (patch.object(sys, "path", [str(scripts), *sys.path]), patch.dict(sys.modules),
                      contextlib.redirect_stdout(output)):
                    importlib.invalidate_caches()
                    sys.modules.pop("my_text", None)
                    self.window.configure()
                    module = sys.modules["my_text"]
                    constructor = module.EditorWindow

                    def run(action):
                        def create(owner):
                            editor = constructor(owner)
                            edit, document = editor.edit, editor.edit.doc
                            created.append((editor.getHWND(), edit, document))
                            def drive():
                                editor.killTimer(drive)
                                try:
                                    action(editor)
                                except BaseException as error:  # noqa: BLE001  # Surface timer assertions outside the native loop.
                                    errors.append(error)
                                finally:
                                    editor.quit()
                            editor.setTimer(drive, 20)
                            return editor
                        with patch.object(module, "EditorWindow", side_effect=create):
                            self.invoke("mytext")
                        self.assertEqual(errors, [])
                        hwnd, edit, document = created[-1]
                        self.assertFalse(user32.IsWindow(hwnd))
                        self.assertNotIn(edit.onDocumentTextModified, document.text_modified_handler_list)
                        self.assertNotIn(edit.onDocumentBookmark, document.bookmark_handler_list)

                    expected = "apple apricot\r\nType here\r\napple"
                    def accept(editor):
                        self.assertFalse(self.window.isEnabled())
                        self.key(ckit.VK_RETURN, window=editor)
                        for ch in "ap":
                            user32.SendMessageW(editor.getHWND(), 0x0102, ord(ch), 1)
                        self.key(ckit.VK_SPACE, ckit.MODKEY_CTRL, window=editor)
                        edit = editor.edit
                        self.assertTrue(edit.isListOpened())
                        self.assertEqual(edit.candidate_window.numItems(), 2)
                        self.key(ckit.VK_RETURN, window=editor)
                        self.assertFalse(edit.isListOpened())
                        self.assertEqual(edit.getText(edit.pointDocumentBegin(), edit.pointDocumentEnd()), expected)
                        self.key(ckit.VK_Z, ckit.MODKEY_CTRL, window=editor)
                        self.assertEqual(edit.getText(edit.point(2, 0), edit.pointDocumentEnd()), "ap")
                        self.key(ckit.VK_Y, ckit.MODKEY_CTRL, window=editor)
                        self.key(ckit.VK_A, ckit.MODKEY_CTRL, window=editor)
                        self.assertEqual(edit.selection.left(), edit.pointDocumentBegin())
                        self.assertEqual(edit.selection.right(), edit.pointDocumentEnd())
                        self.key(ckit.VK_RETURN, ckit.MODKEY_CTRL, window=editor)
                    run(accept)
                    self.assertEqual(output.getvalue(), expected + "\n")
                    self.assertTrue(self.window.isEnabled())
                    output.seek(0)
                    output.truncate(0)
                    run(lambda editor: self.key(ckit.VK_ESCAPE, window=editor))
                    self.assertEqual(output.getvalue(), "Canceled\n")
                    self.assertTrue(self.window.isEnabled())
                    self.window.enable(False)
                    try:
                        run(lambda editor: user32.SendMessageW(editor.getHWND(), 0x0010, 0, 0))
                        self.assertFalse(self.window.isEnabled())
                    finally:
                        self.window.enable(True)

                    def failed_loop(owner):
                        editor = constructor(owner)
                        created.append((editor.getHWND(), editor.edit, editor.edit.doc))
                        def fail():
                            raise RuntimeError("editor loop")
                        editor.messageLoop = fail
                        return editor
                    with (patch.object(module, "EditorWindow", side_effect=failed_loop),
                          self.assertRaisesRegex(RuntimeError, "editor loop")):
                        self.invoke("mytext")
                    self.assertTrue(self.window.isEnabled())
                    hwnd, edit, document = created[-1]
                    self.assertFalse(user32.IsWindow(hwnd))
                    self.assertNotIn(edit.onDocumentTextModified, document.text_modified_handler_list)

            def test_native_documented_extensions(self):
                import clnch_listwindow
                from test_extension_examples import example_sources

                sources = example_sources()
                output = io.StringIO()
                self.assertEqual(self.window.getStringWidth("a\tb", 4, 0), 5)
                self.assertEqual(self.window.getStringWidth("a\tb", 4, 3), 6)
                self.assertEqual(len(self.window.getStringColumns("\U0001f600")), 3)
                origin = self.window.charToClient(0, 0)
                next_cell = self.window.charToClient(1, 1)
                self.assertEqual((next_cell[0] - origin[0], next_cell[1] - origin[1]), self.window.getCharSize())
                scripts = data / "scripts"
                scripts.mkdir(exist_ok=True)
                errors = []
                with (patch.object(sys, "path", [str(scripts), *sys.path]), patch.dict(sys.modules),
                      contextlib.redirect_stdout(output)):
                    (data / "custom.py").write_text(sources["echo_inline"], encoding="utf-8")
                    self.window.configure()
                    self.input_action("myecho;hello world", lambda: self.key(ckit.VK_RETURN))
                    self.assertEqual(output.getvalue(), "hello | world\n")
                    output.seek(0)
                    output.truncate(0)

                    def install(module, setup, name):
                        (scripts / (name + ".py")).write_text(sources[module], encoding="utf-8")
                        importlib.invalidate_caches()
                        sys.modules.pop(name, None)
                        config = sources[setup] + "\n" + sources["list_setup"]
                        (data / "custom.py").write_text(config, encoding="utf-8")
                        self.window.configure()

                    install("echo_module", "echo_setup", "my_echo")
                    self.input_action('myecho;hello "" world', lambda: self.key(ckit.VK_RETURN))
                    self.assertIn("hello |  | world", output.getvalue())
                    def echo_key():
                        self.key(ckit.VK_F9, ckit.MODKEY_CTRL)
                        self.assertEqual(self.window.commandline_edit.getText(), "draft;one")
                    self.input_action("draft;one", echo_key)
                    self.assertIn("Input: draft;one", output.getvalue())

                    install("input_module", "input_setup", "my_input")
                    for text in ("apple", "", None):
                        def respond(text=text):
                            self.window.killTimer(respond)
                            try:
                                edit = self.window.commandline_edit
                                self.assertEqual(edit.candidate_handler(ckit.EditWidget.UpdateInfo("ap", [2, 2])),
                                                 (["apple", "apricot"], 0))
                                edit.setText(text or "")
                                self.key(ckit.VK_ESCAPE if text is None else ckit.VK_RETURN)
                            except BaseException as error:  # noqa: BLE001  # Report native timer assertions and end input safely.
                                errors.append(error)
                                self.window.quit()
                        self.window.active = True
                        self.window.console_window.show(False)
                        self.window.setTimer(respond, 30)
                        self.invoke("myask")
                    self.assertIn("Fruit: apple\n", output.getvalue())
                    self.assertIn("Fruit: \n", output.getvalue())
                    self.assertIn("Canceled\n", output.getvalue())

                    install("menu_module", "menu_setup", "my_menu")
                    create = clnch_listwindow.ListWindow
                    for cancel in (False, True):
                        def created(*args, cancel=cancel, **kwargs):
                            child = create(*args, **kwargs)
                            def choose():
                                child.killTimer(choose)
                                try:
                                    self.key(ckit.VK_N, ckit.MODKEY_CTRL, window=child)
                                    self.key(ckit.VK_ESCAPE if cancel else ckit.VK_RETURN, window=child)
                                except BaseException as error:  # noqa: BLE001  # Surface native menu assertions and release its loop.
                                    errors.append(error)
                                    child.cancel()
                            child.setTimer(choose, 30)
                            return child
                        with patch.object(clnch_listwindow, "ListWindow", side_effect=created):
                            self.invoke("mypick")
                        self.assertTrue(output.getvalue().endswith(
                            "Canceled\n" if cancel else "Choice: downloads\n"))
                    self.assertIn("Choice: downloads\n", output.getvalue())
                    self.assertTrue(self.window.isEnabled())

                    install("dialog_module", "dialog_setup", "my_form")
                    base_dialog = ckit.Dialog
                    for cancel in (False, True):
                        class DrivenDialog(base_dialog):
                            def __init__(child, *args, cancel=cancel, checks=self, **kwargs):
                                super().__init__(*args, **kwargs)
                                def choose(checks=checks):
                                    child.killTimer(choose)
                                    checks.key(ckit.VK_ESCAPE if cancel else ckit.VK_RETURN, window=child)
                                child.setTimer(choose, 30)
                        with patch.object(ckit, "Dialog", DrivenDialog):
                            self.invoke("myform")
                        self.assertTrue(output.getvalue().endswith("Canceled\n" if cancel else "Profile: Alex, 0\n"))
                        self.assertTrue(self.window.isEnabled())

                    install("worker_module", "worker_setup", "my_worker")
                    self.invoke("mycount")
                    self.assertEqual(self.window.simple_status_bar_layer.message, "Count: 20")
                    def cancel_work():
                        self.window.killTimer(cancel_work)
                        self.key(ckit.VK_ESCAPE)
                    self.window.setTimer(cancel_work, 30)
                    self.invoke("mycount")
                    self.assertTrue(output.getvalue().endswith("Canceled\n"))
                    self.assertIsNone(self.window.keydown_hook)
                    self.assertEqual(errors, [])

                    install("job_module", "job_setup", "my_job")
                    self.invoke("myjob")
                    self.pump(lambda: sys.modules["my_job"]._active is None)
                    self.assertEqual(self.window.simple_status_bar_layer.message, "Job: 20")
                    self.invoke("myjob")
                    self.invoke("mycancel")
                    self.pump(lambda: sys.modules["my_job"]._active is None)
                    self.assertTrue(output.getvalue().endswith("Canceled\n"))

            def test_native_auto_complete_default_and_config_changes(self):
                self.window.input_settings.update(HISTORY_MODE="session", COMPLETION_MODE="standard")
                self.window.commandline_history = ["probe_candidate"]
                self.window.commandline_list = []
                user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
                for result, expected in ((None, 0), (1, 1), (-1, 1), (0, 0)):
                    with self.subTest(result=result):
                        if result is not None:
                            with patch.object(clnch_configmenu.clnch_listwindow, "popMenu", return_value=result):
                                clnch_configmenu._configAutoComplete(self.window)
                        def type_character(expected=expected):
                            edit = self.window.commandline_edit
                            self.assertIs(type(edit.getAutoComplete()), int)
                            self.assertEqual(edit.getAutoComplete(), expected)
                            user32.SendMessageW(self.window.getHWND(), 0x0102, ord("p"), 1)
                            self.assertEqual(edit.getText(), "probe_candidate" if expected else "p")
                        self.input_action("", type_character)

            def test_native_mainwindow_startup_dpi_recheck(self):
                # Real HWNDs/fonts, with deterministic monitor-DPI queries.
                for predicted, actual, console_scale in ((1.0, 1.0, 1.0), (1.0, 1.0, 2.0),
                                                         (1.0, 1.5, 2.0), (2.0, 1.0, 1.5)):
                    with (self.subTest(predicted=predicted, actual=actual, console=console_scale),
                          patch.object(ckit.TextWindow, "getDisplayScalingFromPosition", return_value=predicted),
                          patch.object(clnch_mainwindow.MainWindow, "getDisplayScaling", return_value=actual),
                          patch.object(clnch_mainwindow.clnch_consolewindow.ConsoleWindow,
                                       "getDisplayScaling", return_value=console_scale)):
                        window = clnch_mainwindow.MainWindow(debug=True)
                        try:
                            self.assertTrue(window.initialized)
                            for target, scale in ((window, actual), (window.console_window, console_scale)):
                                expected = ckit.getStockedFont("MS Gothic", round(16 * scale), round(2 * scale))
                                self.assertEqual(target.getCharSize(), expected.getCharSize())
                            self.assertEqual(window.console_window.log.snapshot()[2], [""])
                        finally:
                            window.destroy()

            def test_native_mainwindow_dpi_during_base_construction_and_reset(self):
                original_init = ckit.TextWindow.__init__
                original_reset = clnch_mainwindow.MainWindow.resetPos
                events = []

                def initialize(window, **kwargs):
                    if isinstance(window, clnch_mainwindow.MainWindow):
                        window._onDpi(1.5)  # TextPlane and console do not exist yet.
                        events.append("base")
                    original_init(window, **kwargs)

                def reset(window):
                    original_reset(window)
                    window._onDpi(1.5)
                    events.append("reset")

                with (patch.object(ckit.TextWindow, "__init__", new=initialize),
                      patch.object(ckit.TextWindow, "getDisplayScalingFromPosition", return_value=1.0),
                      patch.object(clnch_mainwindow.MainWindow, "getDisplayScaling", return_value=1.5),
                      patch.object(clnch_mainwindow.MainWindow, "resetPos", new=reset)):
                    window = clnch_mainwindow.MainWindow(debug=True)
                    try:
                        self.assertEqual(events, ["base", "reset"])
                        self.assertEqual(window.getCharSize(), ckit.getStockedFont("MS Gothic", 24, 3).getCharSize())
                    finally:
                        window.destroy()

            def test_native_mainwindow_monitor_number_bounds(self):
                monitors = [((0, 0, 1920, 1080), (0, 0, 1920, 1040)),
                            ((-1920, 0, 0, 1080), (-1920, 0, 0, 1040))]
                for count in (1, 2):
                    for number in (0, count - 1, -1, -count, -count - 1, count, count + 1, 10**6):
                        valid = 0 <= number < count
                        expected = monitors[number if valid else 0][0][:2]
                        with (self.subTest(count=count, number=number),
                              patch.object(clnch_mainwindow.pyauto, "Window", wraps=clnch_mainwindow.pyauto.Window) as platform,
                              patch.object(ckit.TextWindow, "getDisplayScalingFromPosition", return_value=1.0) as prediction,
                              patch.object(clnch_mainwindow.MainWindow, "getDisplayScaling", return_value=1.0)):
                            platform.getMonitorInfo.return_value = monitors[:count]
                            clnch_ini.set("GEOMETRY", "monitor", str(number))
                            clnch_ini.set("GEOMETRY", "x", "17")
                            clnch_ini.set("GEOMETRY", "y", "23")
                            window = clnch_mainwindow.MainWindow(debug=True)
                            try:
                                prediction.assert_called_once_with(*expected)
                                position = (expected[0] + 17, expected[1] + 23) if valid else expected
                                self.assertEqual(window.getWindowRect()[:2], position)
                                window.resetPos()
                                self.assertEqual(window.getWindowRect()[:2], position)
                                self.assertEqual(clnch_ini.getint("GEOMETRY", "monitor"), number)
                            finally:
                                window.destroy()

            def test_native_mainwindow_saved_monitor_and_monitor_change(self):
                monitors = [((0, 0, 1920, 1080), (0, 0, 1920, 1040)),
                            ((-1920, 0, 0, 1080), (-1920, 0, 0, 1040))]
                clnch_ini.set("GEOMETRY", "monitor", "1")
                clnch_ini.set("MISC", "inactive_behavior", "none")
                with (patch.object(clnch_mainwindow.pyauto, "Window", wraps=clnch_mainwindow.pyauto.Window) as platform,
                      patch.object(ckit.TextWindow, "getDisplayScalingFromPosition", return_value=1.0) as prediction,
                      patch.object(clnch_mainwindow.MainWindow, "getDisplayScaling", return_value=1.5) as scaling):
                    platform.getMonitorInfo.return_value = monitors
                    window = clnch_mainwindow.MainWindow(debug=True)
                    try:
                        prediction.assert_called_once_with(-1920, 0)
                        rect = window.getWindowRect()
                        initial_width = 18 * ckit.getStockedFont("MS Gothic", 16, 2).getCharSize()[0] + 6
                        self.assertEqual((rect[0] + rect[2], rect[1]), (-3840 + initial_width, 0))
                        self.assertEqual(window.getCharSize(), ckit.getStockedFont("MS Gothic", 24, 3).getCharSize())
                        platform.getMonitorInfo.return_value = monitors[:1]
                        scaling.return_value = 1.0
                        window.onTimerMonitor()
                        rect = window.getWindowRect()
                        self.assertEqual(rect[:2], (0, 0))
                        # Deliver the DPI notification associated with moving to the remaining monitor.
                        window._onDpi(1.0)
                        moved = window.getWindowRect()
                        self.assertEqual((moved[0] + moved[2], moved[1]), (rect[0] + rect[2], rect[1]))
                        self.assertEqual(window.last_monitor_info_list, monitors[:1])
                        self.assertEqual(window.getCharSize(), ckit.getStockedFont("MS Gothic", 16, 2).getCharSize())
                    finally:
                        window.destroy()

            def test_native_mainwindow_runtime_dpi_and_console_independence(self):
                window, console = self.window, self.window.console_window
                console.write("日本語 DPI test", auto_show=False)
                console.selection = [[0, 1], [0, 3]]
                user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
                for scale in (1.0, 1.5, 2.0, 1.0):
                    with (patch.object(clnch_mainwindow.MainWindow, "getDisplayScaling", return_value=scale),
                          patch.object(type(console), "getDisplayScaling", return_value=1.5)):
                        dpi = round(96 * scale)
                        user32.SendMessageW(window.getHWND(), 0x02e0, dpi | dpi << 16, 0)
                        self.assertEqual(window.getCharSize(),
                                         ckit.getStockedFont("MS Gothic", round(16 * scale), round(2 * scale)).getCharSize())
                        self.assertEqual(console.getCharSize(), ckit.getStockedFont("MS Gothic", 24, 3).getCharSize())
                        self.assertEqual(console.selection, [[0, 1], [0, 3]])
                        self.assertEqual(console.log.snapshot()[2], ["日本語 DPI test"])
                clnch_ini.set("FONT", "size", "20")
                with (patch.object(clnch_mainwindow.MainWindow, "getDisplayScaling", return_value=1.0),
                      patch.object(type(console), "getDisplayScaling", return_value=2.0)):
                    window.updateFont()
                    self.assertEqual(window.getCharSize(), ckit.getStockedFont("MS Gothic", 20, 2).getCharSize())
                    self.assertEqual(console.getCharSize(), ckit.getStockedFont("MS Gothic", 40, 4).getCharSize())

            def test_native_console_copy_eviction_resize_and_font(self):
                console = self.window.console_window
                console.clearLog()
                source = [f"日本語\tline {i} " + "long path/" * 8 for i in range(1000)]
                console.log.write("\r\n".join(source))
                console.setPosSize(0, 0, 32, 12, 0)
                console.paint()
                console._scroll(-10**6)
                console._scroll(30)
                anchor = console._getRows()[console.scroll_info.pos]
                console.selection = [[998, 1], [999, len(source[-1])]]
                console.log.write("\r")
                console.paint()
                console.log.write("\nnew")
                console._copySelectedRegion()
                self.assertEqual(ckit.getClipboardText(), source[-2][1:] + "\r\n" + source[-1])
                self.assertEqual(console._getRows()[console.scroll_info.pos], anchor)
                for scale in (1.0, 1.5, 2.0):
                    console._onDpi(scale)
                    for width in (12, 32, 80):
                        console.setPosSize(0, 0, width, 12, 0)
                        console.paint()
                        rows = console._getRows()
                        layout = console._wrap_cache["layout"]
                        text = source[-1]
                        parts = [text[start:end] for line, start, end in rows if line == 999]
                        self.assertEqual("".join(parts), text)
                        self.assertTrue(all(console.getStringWidth(ckit.expandTab(console, part)) <= console.width()
                                            for part in parts))
                        self.assertEqual(layout.first_line, 1)
                self.key(ckit.VK_A, ckit.MODKEY_CTRL, console)
                self.key(ckit.VK_C, ckit.MODKEY_CTRL, console)
                self.assertEqual(ckit.getClipboardText(), "\r\n".join(source[1:] + ["new"]))
                console._scroll(10**6)
                console.write("\nlast", auto_show=False)
                self.assertEqual(console.scroll_info.pos,
                                 max(len(console._getRows()) - max(console.rectText()[3], 1), 0))

            def test_native_console_newline_copy_and_partial_selection(self):
                console = self.window.console_window
                for chunks in (("abcdefghi\n日本\t🙂\ntail\r",),
                               ("abcdefghi\r\n日本\t🙂\r\ntail\r",),
                               ("abcdefghi\r", "", "\n日本\t🙂\r", "\ntail\r")):
                    with self.subTest(chunks=chunks):
                        console.clearLog()
                        console.setPosSize(0, 0, 6, 12, 0)
                        for chunk in chunks:
                            console.write(chunk, auto_show=False)
                            console.paint()
                        self.assertGreater(len(console._getRows()), 3)
                        self.key(ckit.VK_A, ckit.MODKEY_CTRL, console)
                        self.key(ckit.VK_C, ckit.MODKEY_CTRL, console)
                        self.assertEqual(ckit.getClipboardText(), "abcdefghi\r\n日本\t🙂\r\ntail\r")
                        console.selection = [[1, 3], [0, 2]]
                        console._copySelectedRegion()
                        self.assertEqual(ckit.getClipboardText(), "cdefghi\r\n日本\t")
                        console.selection = [[0, 2], [0, 8]]
                        console._copySelectedRegion()
                        self.assertEqual(ckit.getClipboardText(), "cdefgh")

            def test_native_console_mouse_copy_and_clear_capture(self):
                console = self.window.console_window
                console.clearLog()
                console.write("alpha beta\r\n日本語\tlast", auto_show=False)
                console.show(True)
                console._scroll(-10**6)
                user32.GetCapture.restype = wintypes.HWND
                def mouse(message, column=0):
                    x, y = console.charToClient(column, 0)
                    user32.SendMessageW(console.getHWND(), message, 1, (y << 16) | x)
                mouse(0x0201)
                self.assertEqual(user32.GetCapture(), console.getHWND())
                mouse(0x0202)
                mouse(0x0203, 1)
                mouse(0x0202, 1)
                self.assertEqual(ckit.getClipboardText(), "alpha ")
                mouse(0x0201, 1)
                self.assertEqual(console.mouse_click_info[0], "all")
                mouse(0x0202, 1)
                self.assertEqual(ckit.getClipboardText(), "alpha beta\r\n日本語\tlast")
                mouse(0x0201)
                self.assertEqual(user32.GetCapture(), console.getHWND())
                console.clearLog()
                self.assertFalse(user32.GetCapture())
                self.assertIsNone(console.mouse_click_info)
                self.assertEqual(console.selection, [[0, 0], [0, 0]])

            def test_native_console_stdio_auto_show_request_and_close(self):
                console = self.window.console_window
                console.clearLog()
                console.show(False)
                console.setAutoShow(True)
                console.registerStdio()
                try:
                    sys.stdout.write("stdout日本語\n")
                    sys.stderr.write("stderr\tline")
                finally:
                    console.unregisterStdio()
                self.pump(lambda: console.opened)
                self.assertFalse(console.auto_show_required)
                self.assertEqual(console.log.snapshot()[2], ["stdout日本語", "stderr\tline"])
                self.key(ckit.VK_ESCAPE, window=console)
                self.assertFalse(console.opened)
                self.assertFalse(console.isVisible())
                self.assertTrue(self.window.isEnabled())

            def test_native_owned_activation_and_external_exit(self):
                import pyauto

                self.modal_desktop_state()
                window = self.window
                external = ckit.TextWindow(x=30, y=30, width=30, height=3,
                    title="ReCraftLaunch activation test target", show=False)
                self.addCleanup(external.destroy)
                if interactive_foreground:
                    source = PROBE.replace('output = Path(sys.argv[1])',
                        'result["hwnd"] = hwnd\n    output = Path(sys.argv[1])')
                    source = source.replace('finally:\n    u.DestroyWindow(hwnd)',
                        '    import time\n'
                        '    message = w.MSG()\n'
                        '    while not output.with_suffix(".stop").exists():\n'
                        '        u.AllowSetForegroundWindow(int(sys.argv[2]))\n'
                        '        while u.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):\n'
                        '            u.TranslateMessage(ctypes.byref(message))\n'
                        '            u.DispatchMessageW(ctypes.byref(message))\n'
                        '        time.sleep(0.01)\n'
                        'finally:\n    u.DestroyWindow(hwnd)')
                    child_source = data / "activation-child.py"
                    ready = data / "activation-child.json"
                    child_source.write_text(source, encoding="utf-8")
                    process = subprocess.Popen([str(pythonw), "-B", "-S", str(child_source),
                                                str(ready), str(os.getpid())])
                    def stop_child():
                        ready.with_suffix(".stop").touch()
                        try:
                            process.wait(timeout=3)
                        finally:
                            if process.poll() is None:
                                process.kill()
                                process.wait()
                    self.addCleanup(stop_child)
                    self.pump(ready.exists)
                    hwnd = json.loads(ready.read_text(encoding="utf-8"))["hwnd"]
                    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
                    external = SimpleNamespace(getHWND=lambda: hwnd, show=lambda *args: None,
                        foreground=lambda: user32.SetForegroundWindow(hwnd), activate=lambda: None)
                front = [window]
                def activate(target):
                    if interactive_foreground:
                        target.show(True, False)
                        target.foreground()
                        target.activate()
                        self.pump(lambda: user32.GetForegroundWindow() == target.getHWND(), timeout=2)
                    else:
                        # Private stations cannot acquire foreground; retain real HWND/owner APIs.
                        user32.SendMessageW(front[0].getHWND(), 0x0006, 0, target.getHWND())
                        front[0] = target
                        user32.SendMessageW(target.getHWND(), 0x0006, 1, 0)
                def wait_tick():
                    start = time.monotonic()
                    self.pump(lambda: time.monotonic() - start >= 0.05, timeout=1)
                original_loop = ckit.TextWindow.messageLoop
                for clear, operation in ((True, "cancel"), (False, "cancel"),
                        (True, "submenu"), (False, "enable_clear"),
                        (True, "main_external"), (False, "main_external"),
                        (True, "config_external"), (False, "config_external"),
                        (True, "screens"), (True, "console"), (False, "console")):
                    with self.subTest(clear=clear, operation=operation), ExitStack() as cleanup:
                        if not interactive_foreground:
                            cleanup.enter_context(patch.object(clnch_mainwindow, "pyauto", SimpleNamespace(
                                Window=SimpleNamespace(getForeground=lambda: pyauto.Window.fromHWND(front[0].getHWND()),
                                                       getMonitorInfo=pyauto.Window.getMonitorInfo))))
                        window.input_settings["CLEAR_ON_DEACTIVATE"] = clear
                        window.commandline_history[:] = ["history sentinel"]
                        activate(window)
                        steps = iter([1, 4, 1, -1, -1] if operation == "enable_clear"
                                     else [1, -1, -1] if operation == "submenu" else [-1])
                        errors, handles = [], []
                        def modal_loop(child, *args, operation=operation, clear=clear,
                                       steps=steps, handles=handles, errors=errors):
                            if child is window:
                                return original_loop(child, *args)
                            handles.append(child.getHWND())
                            previous = front[0]
                            activate(child)
                            def drive():
                                child.killTimer(drive)
                                try:
                                    self.assertFalse(window.isEnabled())
                                    self.assertTrue(window.isLauncherActive())
                                    owner = pyauto.Window.fromHWND(child.getHWND())
                                    while owner and owner.getHWND() != window.getHWND():
                                        owner = owner.getOwner()
                                    self.assertIsNotNone(owner)
                                    self.assertEqual(window.commandline_edit.getText(), "draft 日本語")
                                    self.assertEqual(window.commandline_edit.getSelection(), [1, 4])
                                    if operation == "config_external":
                                        activate(external)
                                        wait_tick()
                                        self.assertFalse(window.isLauncherActive())
                                        self.assertEqual(window.commandline_edit.getText(), "" if clear else "draft 日本語")
                                        window.hotkey_Activate()
                                        if not interactive_foreground:
                                            activate(child)
                                        wait_tick()
                                        self.assertTrue(window.isLauncherActive())
                                    if operation == "screens" and isinstance(child, clnch_cmdeditor.CommandEditor):
                                        import clnch_msgbox

                                        clnch_msgbox.popMessageBox(child, 0, "Nested", "Owned confirmation")
                                        self.assertTrue(child.isEnabled())
                                    selected = next(steps, -1)
                                    if selected >= 0:
                                        self.key(ckit.VK_HOME, window=child)
                                        for _ in range(selected):
                                            self.key(ckit.VK_DOWN, window=child)
                                        self.key(ckit.VK_RETURN, window=child)
                                    else:
                                        self.key(ckit.VK_ESCAPE, window=child)
                                except BaseException as error:  # noqa: BLE001  # Close the modal loop before surfacing assertions.
                                    errors.append(error)
                                    child.quit()
                            child.setTimer(drive, 40)
                            try:
                                return original_loop(child, *args)
                            finally:
                                child.killTimer(drive)
                                if not interactive_foreground:
                                    activate(previous)
                        def operate(operation=operation, clear=clear, errors=errors, modal_loop=modal_loop):
                            edit = window.commandline_edit
                            edit.setSelection([1, 4])
                            if operation == "main_external":
                                activate(external)
                                wait_tick()
                                self.assertFalse(window.isLauncherActive())
                                window.hotkey_Activate()
                                if not interactive_foreground:
                                    activate(window)
                            elif operation == "console":
                                window.command_ConsoleOpen(None)
                                if not interactive_foreground:
                                    activate(window.console_window)
                                wait_tick()
                                self.assertEqual(edit.getText(), "draft 日本語")
                                activate(external)
                                wait_tick()
                                self.assertEqual(edit.getText(), "" if clear else "draft 日本語")
                                window.hotkey_Activate()
                                if not interactive_foreground:
                                    activate(window)
                                wait_tick()
                                self.assertTrue(window.console_window.opened)
                                window.command_ConsoleClose(None)
                            else:
                                with patch.object(ckit.TextWindow, "messageLoop", modal_loop):
                                    if operation == "screens":
                                        for name, opener in self.modal_openers():
                                            opener()
                                    else:
                                        self.key(ord("S"), ckit.MODKEY_CTRL)
                            self.assertEqual(errors, [])
                            expected = "" if clear and (operation.endswith("external") or operation == "console") else "draft 日本語"
                            self.assertIs(window.commandline_edit, edit)
                            self.assertEqual(edit.getText(), expected)
                            if expected:
                                self.assertEqual(edit.getSelection(), [1, 4])
                            self.assertEqual(window.commandline_history, ["history sentinel"])
                            self.assertTrue(window.isEnabled())
                            if operation == "enable_clear":
                                self.assertTrue(window.input_settings["CLEAR_ON_DEACTIVATE"])
                                self.assertEqual(clnch_ini.get("INPUT", "clear_on_deactivate"), "1")
                        self.input_action("draft 日本語", operate)
                        self.assertTrue(all(not user32.IsWindow(hwnd) for hwnd in handles))

            def test_native_config_hierarchy_selection_refresh_and_input_return(self):
                import clnch_listwindow
                plan = iter([
                    (strings.CONFIG_TITLE, 0, 1),
                    (strings.CONFIG_INPUT, 0, 1),
                    (strings.CONFIG_AUTO_COMPLETE, 0, 1),
                    (strings.CONFIG_INPUT, 1, 5),
                    (strings.INPUT_SPACE, 0, 1),
                    (strings.CONFIG_INPUT, 5, -1),
                    (strings.CONFIG_TITLE, 1, 0),
                    (strings.CONFIG_APPEARANCE, 0, 3),
                    (strings.CONFIG_MIN_SIZE, 6, 12),
                    (strings.CONFIG_APPEARANCE, 3, -1),
                    (strings.CONFIG_TITLE, 0, -1),
                ])
                original = clnch_listwindow.ListWindow
                frames, errors = [], []
                def create(*args, **kwargs):
                    listing = original(*args, **kwargs)
                    def drive():
                        listing.killTimer(drive)
                        try:
                            title, initial, selected = next(plan)
                            self.assertEqual(args[8], title)
                            self.assertEqual(listing.select, initial)
                            self.assertFalse(self.window.isEnabled())
                            frames.append([item[0] if isinstance(item, tuple) else item for item in args[9]])
                            if selected < 0:
                                self.key(ckit.VK_ESCAPE, window=listing)
                            else:
                                self.key(ckit.VK_HOME, window=listing)
                                for _ in range(selected):
                                    self.key(ckit.VK_DOWN, window=listing)
                                self.key(ckit.VK_RETURN, window=listing)
                        except BaseException as error:  # noqa: BLE001  # Surface timer failures and exit the isolated modal loop.
                            errors.append(error)
                            listing.cancel()
                    listing.setTimer(drive, 30)
                    return listing
                custom_runs = self.window.custom_runs
                # The private station cannot retain normal desktop activation.
                self.window.input_settings["CLEAR_ON_DEACTIVATE"] = False
                space, tab = lambda info: None, lambda info: None
                self.window.keymap["Space"] = space
                self.window.cmd_keymap["Tab"] = tab
                self.window.commandline_history[:] = ["history retained"]
                def open_config():
                    edit = self.window.commandline_edit
                    self.assertEqual(edit.getText(), "keep 日本語 input")
                    edit.setSelection([1, 4])
                    with patch.object(clnch_listwindow, "ListWindow", side_effect=create):
                        self.key(83, 2)
                    self.assertEqual(errors, [])
                    self.assertEqual(len(frames), 11)
                    self.assertIs(self.window.commandline_edit, edit)
                    self.assertEqual(edit.getText(), "keep 日本語 input")
                    self.assertEqual(edit.getSelection(), [1, 4])
                    self.assertTrue(self.window.isEnabled())
                self.input_action("keep 日本語 input", open_config)
                self.assertEqual(errors, [])
                self.assertEqual(len(frames), 11)
                self.assertEqual(len(frames[1]), 7)
                self.assertIn(strings.AUTO_COMPLETE_ON, frames[3][1])
                self.assertIn(strings.INPUT_SPACE_COMPLETE, frames[5][5])
                self.assertIn("24", frames[9][3])
                self.assertEqual(clnch_ini.getint("GEOMETRY", "min_width"), 24)
                self.assertEqual(self.window.input_settings["SPACE_ACTION"], "complete")
                self.assertEqual(self.window.custom_runs, custom_runs)
                self.assertIs(self.window.keymap["Space"], space)
                self.assertIs(self.window.cmd_keymap["Tab"], tab)
                self.assertEqual(self.window.commandline_history, ["history retained"])

            def test_native_config_language_save_cancel_and_pending_value(self):
                import configparser

                import clnch_msgbox

                original = ckit.TextWindow.messageLoop
                selections = iter((ckit.VK_RETURN, ckit.VK_ESCAPE))
                errors = []
                def message_loop(dialog, *args, **kwargs):
                    key = next(selections)
                    def drive():
                        dialog.killTimer(drive)
                        try:
                            self.assertFalse(self.window.isEnabled())
                            self.key(ckit.VK_END, window=dialog)
                            self.key(key, window=dialog)
                        except BaseException as error:  # noqa: BLE001  # Report isolated native timer failures.
                            errors.append(error)
                            dialog.cancel()
                    dialog.setTimer(drive, 30)
                    return original(dialog, *args, **kwargs)
                clnch_ini.set("MISC", "language", "ja")
                clnch_ini.write()
                with patch.object(ckit.TextWindow, "messageLoop", message_loop), \
                     patch.object(clnch_msgbox, "popMessageBox") as notice:
                    clnch_configmenu._configLanguage(self.window)
                    saved = Path(clnch_ini.ini_filename).read_bytes()
                    parser = configparser.RawConfigParser()
                    parser.read_string(saved.decode("utf-8"))
                    self.assertEqual(parser.get("MISC", "language"), "en")
                    self.assertEqual(strings.get_language(), "ja")
                    self.assertIn("English", clnch_configmenu._languageValue())
                    self.assertEqual(notice.call_args.args[-1], strings.LANGUAGE_RESTART)
                    self.assertTrue(self.window.isEnabled())
                    clnch_configmenu._configLanguage(self.window)
                    self.assertEqual(Path(clnch_ini.ini_filename).read_bytes(), saved)
                    notice.assert_called_once()
                    self.assertTrue(self.window.isEnabled())
                self.assertEqual(errors, [])

            def test_native_config_hotkey_assign_cancel_and_reregister(self):
                original = ckit.TextWindow.messageLoop
                errors, seen = [], []
                key, modifier = ckit.VK_F9, ckit.MODKEY_CTRL
                def message_loop(dialog, *args, **kwargs):
                    if type(dialog).__name__ == "HotKeyWindow":
                        def drive():
                            dialog.killTimer(drive)
                            try:
                                self.assertFalse(self.window.isEnabled())
                                self.key(key, modifier, window=dialog)
                                self.key(ckit.VK_ESCAPE if seen else ckit.VK_RETURN, window=dialog)
                                seen.append(dialog.getResult())
                            except BaseException as error:  # noqa: BLE001  # Surface timer failures and exit the isolated modal loop.
                                errors.append(error)
                                dialog.onClose()
                        dialog.setTimer(drive, 30)
                    return original(dialog, *args, **kwargs)
                with patch.object(ckit.TextWindow, "messageLoop", message_loop), \
                     patch.object(self.window, "killHotKey") as kill, \
                     patch.object(self.window, "setHotKey") as register:
                    clnch_configmenu._configHotKeyAssign(self.window)
                    self.assertEqual(clnch_ini.getint("HOTKEY", "activate_vk"), key)
                    self.assertEqual(clnch_ini.getint("HOTKEY", "activate_mod"), modifier)
                    self.assertTrue(self.window.isEnabled())
                    register.assert_called_once_with(key, modifier, self.window.hotkey_Activate)
                    kill.assert_not_called()
                    key = ckit.VK_F10
                    clnch_configmenu._configHotKeyAssign(self.window)
                    self.assertEqual(clnch_ini.getint("HOTKEY", "activate_vk"), ckit.VK_F9)
                    self.assertEqual(register.call_count, 1)
                    self.assertTrue(self.window.isEnabled())
                self.assertEqual(errors, [])
                self.assertEqual(seen, [[[ckit.VK_F9, modifier]], None])

            def test_native_config_hotkey_modifier_warning_returns_and_preserves_candidate(self):
                import clnch_msgbox

                old, new = (ckit.VK_F9, 2), (ckit.VK_F10, 6)
                original_loop = ckit.TextWindow.messageLoop
                errors, warnings, handles = [], [], []
                active = [None]
                phase = None
                def saved_hotkey():
                    parser = configparser.RawConfigParser()
                    parser.read(clnch_ini.ini_filename, encoding="utf-8")
                    return dict(parser["HOTKEY"])
                user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
                user32.GetWindow.restype = wintypes.HWND
                user32.IsWindow.argtypes = (wintypes.HWND,)
                def message_loop(dialog, *args, **kwargs):
                    def drive():
                        dialog.killTimer(drive)
                        try:
                            self.assertFalse(self.window.isEnabled())
                            if isinstance(dialog, clnch_msgbox.MessageBox):
                                parent = active[0]
                                self.assertFalse(parent.isEnabled())
                                self.assertTrue(dialog.isEnabled())
                                self.assertEqual(user32.GetWindow(dialog.getHWND(), 4), parent.getHWND())
                                self.assertEqual(dialog.message, strings.HOTKEY_MODIFIER_ONLY)
                                self.assertIsNone(parent.getResult())
                                self.assertEqual(self.window._registered_hotkey, old)
                                self.assertEqual((clnch_ini.getint("HOTKEY", "activate_vk"),
                                                  clnch_ini.getint("HOTKEY", "activate_mod")), old)
                                self.assertEqual(saved_hotkey(), before)
                                warnings.append(parent.activate_hotkey.getValue())
                                handles.append(dialog.getHWND())
                                self.key(ckit.VK_RETURN, window=dialog)
                                return
                            active[0] = dialog
                            handles.append(dialog.getHWND())
                            keys = (ckit.VK_CONTROL, ckit.VK_LCONTROL, ckit.VK_RCONTROL,
                                    ckit.VK_SHIFT, ckit.VK_LSHIFT, ckit.VK_RSHIFT,
                                    ckit.VK_MENU, ckit.VK_LMENU, ckit.VK_RMENU, ckit.VK_LWIN, ckit.VK_RWIN)
                            for vk in keys if phase == "cancel" else (ckit.VK_CONTROL,):
                                for mod in (0, 7):
                                    count = len(warnings)
                                    self.key(vk, mod, window=dialog)
                                    candidate = dialog.activate_hotkey.getValue()
                                    self.assertEqual(len(warnings), count)
                                    self.key(ckit.VK_RETURN, window=dialog)
                                    self.assertEqual(len(warnings), count + 1)
                                    self.assertEqual(dialog.activate_hotkey.getValue(), candidate)
                                    self.assertTrue(dialog.isEnabled())
                                    self.assertFalse(self.window.isEnabled())
                                    self.assertFalse(user32.IsWindow(handles[-1]))
                            if phase == "clear":
                                self.key(ckit.VK_DELETE, window=dialog)
                            elif phase == "reassign":
                                self.key(*new, window=dialog)
                            self.key(ckit.VK_ESCAPE if phase == "cancel" else ckit.VK_RETURN, window=dialog)
                        except BaseException as error:  # noqa: BLE001  # Exit native loops before surfacing timer assertions.
                            errors.append(error)
                            dialog.onClose()
                    dialog.setTimer(drive, 20)
                    return original_loop(dialog, *args, **kwargs)
                with patch.object(self.window, "setHotKey") as register, \
                     patch.object(self.window, "killHotKey") as kill, \
                     patch.object(ckit.TextWindow, "messageLoop", message_loop):
                    for phase in ("cancel", "clear", "reassign"):
                        self.window._registered_hotkey = old
                        clnch_ini.set("HOTKEY", "activate_vk", str(old[0]))
                        clnch_ini.set("HOTKEY", "activate_mod", str(old[1]))
                        clnch_ini.write()
                        before = saved_hotkey()
                        register.reset_mock()
                        kill.reset_mock()
                        clnch_configmenu._configHotKeyAssign(self.window)
                        self.assertEqual(errors, [])
                        self.assertTrue(self.window.isEnabled())
                        expected = old if phase == "cancel" else (0, 0) if phase == "clear" else new
                        self.assertEqual(self.window._registered_hotkey, expected)
                        self.assertEqual((clnch_ini.getint("HOTKEY", "activate_vk"),
                                          clnch_ini.getint("HOTKEY", "activate_mod")), expected)
                        if phase == "reassign":
                            register.assert_called_once_with(*new, self.window.hotkey_Activate)
                        else:
                            register.assert_not_called()
                        if phase == "cancel":
                            kill.assert_not_called()
                            self.assertEqual(saved_hotkey(), before)
                        else:
                            kill.assert_called_once_with(self.window.hotkey_Activate)
                self.assertTrue(warnings)
                self.assertTrue(all(not user32.IsWindow(hwnd) for hwnd in handles))

            def test_native_config_hotkey_delete_accept_cancel_and_reassign(self):
                import configparser
                old = (ckit.VK_F9, ckit.MODKEY_CTRL)
                new = (ckit.VK_F10, ckit.MODKEY_CTRL)
                phase = None
                def drive(dialog, *args, **kwargs):
                    self.assertEqual(type(dialog).__name__, "HotKeyWindow")
                    self.assertFalse(self.window.isEnabled())
                    if phase == "cancel":
                        for modifier in (ckit.MODKEY_CTRL, ckit.MODKEY_ALT, ckit.MODKEY_SHIFT):
                            self.key(ckit.VK_DELETE, modifier, window=dialog)
                            self.assertEqual(dialog.activate_hotkey.getValue(), [ckit.VK_DELETE, modifier])
                        dialog.onKeyDown(ckit.VK_DELETE, ckit.MODKEY_WIN)
                        self.assertEqual(dialog.activate_hotkey.getValue(), [ckit.VK_DELETE, ckit.MODKEY_WIN])
                    self.key(ckit.VK_DELETE, window=dialog)
                    self.assertEqual(dialog.activate_hotkey.getValue(), [0, 0])
                    with patch.object(dialog, "putString", wraps=dialog.putString) as draws:
                        dialog.paint()
                    row = [entry.args[-1] for entry in draws.call_args_list if entry.args[1] == 0]
                    self.assertEqual(row[-1].strip(), strings.HOTKEY_UNASSIGNED)
                    register.assert_not_called()
                    kill.assert_not_called()
                    if phase == "reassign":
                        self.key(*new, window=dialog)
                    self.key(ckit.VK_ESCAPE if phase == "cancel" else ckit.VK_RETURN, window=dialog)
                with patch.object(self.window, "setHotKey") as register, \
                     patch.object(self.window, "killHotKey") as kill, \
                     patch.object(clnch_mainwindow.clnch_msgbox, "popMessageBox") as notice, \
                     patch.object(ckit.TextWindow, "messageLoop", drive):
                    self.assertTrue(self.window.updateHotKey(*old))
                    clnch_ini.set("HOTKEY", "activate_vk", str(old[0]))
                    clnch_ini.set("HOTKEY", "activate_mod", str(old[1]))
                    for phase in ("cancel", "reject", "accept", "already_unset", "reassign"):
                        with self.subTest(phase=phase):
                            register.reset_mock()
                            kill.reset_mock()
                            kill.side_effect = OSError("unregister rejected") if phase == "reject" else None
                            clnch_configmenu._configHotKeyAssign(self.window)
                            expected = old if phase in ("cancel", "reject") else new if phase == "reassign" else (0, 0)
                            self.assertEqual(self.window._registered_hotkey, expected)
                            self.assertEqual((clnch_ini.getint("HOTKEY", "activate_vk"),
                                              clnch_ini.getint("HOTKEY", "activate_mod")), expected)
                            clnch_ini.write()
                            saved = configparser.RawConfigParser()
                            saved.read(clnch_ini.ini_filename, encoding="utf-8")
                            self.assertEqual((saved.getint("HOTKEY", "activate_vk"),
                                              saved.getint("HOTKEY", "activate_mod")), expected)
                            self.assertTrue(self.window.isEnabled())
                            if phase in ("reject", "accept"):
                                kill.assert_called_once_with(self.window.hotkey_Activate)
                            else:
                                kill.assert_not_called()
                            if phase == "reassign":
                                register.assert_called_once_with(*new, self.window.hotkey_Activate)
                            else:
                                register.assert_not_called()
                    notice.assert_called_once()

            def test_native_startup_hotkey_failure_keeps_recovery_ui(self):
                clnch_ini.set("HOTKEY", "activate_vk", str(ckit.VK_F24))
                messages = []
                original = ckit.TextWindow.messageLoop
                def drive(dialog, *args, **kwargs):
                    if isinstance(dialog, clnch_mainwindow.clnch_msgbox.MessageBox):
                        messages.append(dialog.message)
                        dialog.onKeyDown(ckit.VK_RETURN, 0)
                        return
                    return original(dialog, *args, **kwargs)
                with patch.object(clnch_mainwindow.MainWindow, "setHotKey", side_effect=OSError("startup rejection")), \
                     patch.object(ckit.TextWindow, "messageLoop", drive):
                    window = clnch_mainwindow.MainWindow()
                    try:
                        self.assertTrue(window.initialized)
                        self.assertTrue(window.isEnabled())
                        self.assertEqual(window._registered_hotkey, (0, 0))
                        window.configure()
                        self.assertIn("config", dict(window.launcher.command_list))
                        self.assertEqual(len(messages), 1)
                        self.assertIn(strings.HOTKEY_REGISTER_ERROR, messages[0])
                        self.assertIn("startup rejection", messages[0])
                        self.assertEqual(clnch_ini.getint("HOTKEY", "activate_vk"), ckit.VK_F24)
                    finally:
                        window.destroy()

            def test_native_startup_modifier_hotkey_is_rejected_without_ini_rewrite(self):
                clnch_ini.set("HOTKEY", "activate_vk", str(ckit.VK_RCONTROL))
                clnch_ini.set("HOTKEY", "activate_mod", "4")
                messages = []
                def drive(dialog, *args, **kwargs):
                    self.assertIsInstance(dialog, clnch_mainwindow.clnch_msgbox.MessageBox)
                    messages.append(dialog.message)
                    self.key(ckit.VK_RETURN, window=dialog)
                with patch.object(clnch_mainwindow.MainWindow, "setHotKey") as register, \
                     patch.object(ckit.TextWindow, "messageLoop", drive), \
                     patch.object(clnch_ini, "set", wraps=clnch_ini.set) as save:
                    window = clnch_mainwindow.MainWindow()
                    try:
                        self.assertTrue(window.initialized)
                        self.assertTrue(window.isEnabled())
                        self.assertEqual(window._registered_hotkey, (0, 0))
                        window.configure()
                        self.assertIn("config", dict(window.launcher.command_list))
                        self.assertEqual(messages, [strings.HOTKEY_MODIFIER_ONLY])
                        register.assert_not_called()
                        self.assertFalse(any(call.args[:2] in (("HOTKEY", "activate_vk"),
                                                              ("HOTKEY", "activate_mod"))
                                             for call in save.call_args_list))
                        self.assertEqual(clnch_ini.getint("HOTKEY", "activate_vk"), ckit.VK_RCONTROL)
                        self.assertEqual(clnch_ini.getint("HOTKEY", "activate_mod"), 4)
                    finally:
                        window.destroy()

            def test_native_hotkey_error_sentence_layout(self):
                import clnch_strings_en
                import clnch_strings_ja
                cases = (
                    (clnch_strings_ja, clnch_strings_ja.HOTKEY_REGISTER_ERROR,
                     ["ホットキーを適用できませんでした。", "ホットキーの割り当ては変更していません。"]),
                    (clnch_strings_ja, clnch_strings_ja.HOTKEY_RESTORE_ERROR,
                     ["以前のホットキーも復元できませんでした。", "Configでホットキーを再設定してください。"]),
                    (clnch_strings_en, clnch_strings_en.HOTKEY_REGISTER_ERROR,
                     ["Could not apply the hotkey.", "The hotkey assignment was not changed."]),
                    (clnch_strings_en, clnch_strings_en.HOTKEY_RESTORE_ERROR,
                     ["The previous hotkey could not be restored.", "Assign a hotkey again in Config."]),
                )
                for language, message, expected in cases:
                    with self.subTest(language=language.__name__, message=message), \
                         patch.object(clnch_mainwindow.clnch_msgbox, "strings", language):
                        box = clnch_mainwindow.clnch_msgbox.MessageBox(
                            300, 250, self.window, show=False,
                            title=language.ERROR_TITLE,
                            message=message + "\n[WinError 1409] そのホット キーは既に登録されています。")
                        try:
                            self.assertEqual(box.message_lines[:2], expected)
                            self.assertNotIn("。", box.message_lines)
                            self.assertNotIn(".", box.message_lines)
                        finally:
                            box.destroy()

            def test_native_hotkey_failure_keeps_ini_and_old_setting(self):
                import configparser
                # Actual GUI/settings; OS registration is covered on WinSta0 separately.
                def register(key, modifier, callback):
                    if key == ckit.VK_F24:
                        raise OSError("registration conflict")
                original = ckit.TextWindow.messageLoop
                def drive(dialog, *args, **kwargs):
                    if type(dialog).__name__ == "HotKeyWindow":
                        dialog.activate_hotkey.onKeyDown(ckit.VK_F24, ckit.MODKEY_CTRL)
                        dialog.onEnter()
                        return
                    return original(dialog, *args, **kwargs)
                with patch.object(self.window, "setHotKey", side_effect=register), \
                     patch.object(self.window, "killHotKey"), \
                     patch.object(ckit.TextWindow, "messageLoop", drive), \
                     patch.object(clnch_mainwindow.clnch_msgbox, "popMessageBox") as notice:
                    self.assertTrue(self.window.updateHotKey(ckit.VK_F23, ckit.MODKEY_CTRL))
                    clnch_ini.set("HOTKEY", "activate_vk", str(ckit.VK_F23))
                    clnch_ini.set("HOTKEY", "activate_mod", str(ckit.MODKEY_CTRL))
                    clnch_ini.write()
                    before = configparser.RawConfigParser()
                    before.read(clnch_ini.ini_filename, encoding="utf-8")
                    clnch_configmenu._configHotKeyAssign(self.window)
                    notice.assert_called_once()
                    self.assertEqual(self.window._registered_hotkey, (ckit.VK_F23, ckit.MODKEY_CTRL))
                    self.assertEqual(clnch_ini.getint("HOTKEY", "activate_vk"), ckit.VK_F23)
                    clnch_ini.write()
                    saved = configparser.RawConfigParser()
                    saved.read(clnch_ini.ini_filename, encoding="utf-8")
                    self.assertEqual(dict(saved["HOTKEY"]), dict(before["HOTKEY"]))
                    self.assertTrue(self.window.isEnabled())

            def test_native_initial_custom_failure_keeps_recovery_commands(self):
                import clnch_listwindow

                self.assertTrue(self.doCleanups())
                config = data / "custom.py"
                for source in ('def broken(\n', 'raise RuntimeError("load failed")\n',
                               'raise SystemExit("load exit")\n', 'raise KeyboardInterrupt("load interrupt")\n',
                               'configure = None\n', 'configure_ListWindow = 1\n'):
                    with self.subTest(source=source):
                        config.write_text(source, encoding="utf-8")
                        self.window = clnch_mainwindow.MainWindow()
                        self.window.console_window.unregisterStdio()
                        try:
                            with redirect_stderr(io.StringIO()) as errors, \
                                    contextlib.redirect_stdout(io.StringIO()) as output:
                                self.window.command_Reload(None)
                            self.assertTrue(errors.getvalue())
                            self.assertEqual(output.getvalue(), "")
                            self.assertTrue(self.window._config_failed)
                            self.assertIsNone(self.window.custom)
                            self.assertEqual(ckit.ckit_userconfig.user_namespace, {})
                            self.assertTrue({"config", "reload", "quit", "new", "_ra"}
                                            <= dict(self.window.launcher.command_list).keys())
                            for key, name in (("C-S", "ConfigMenu"), ("C-F10", "ConsoleToggle"), ("F1", "Help")):
                                self.assertEqual(self.window.keymap[key].name, name)
                                self.assertIs(self.window.keymap[key].owner, self.window)
                            listing = clnch_listwindow.ListWindow(0, 0, 10, 1, 20, 4, self.window,
                                                                 show=False, title="Recovery", items=["item"])
                            listing.destroy()
                            config.write_text('def configure(window):\n    window.recovered = True\n', encoding="utf-8")
                            with contextlib.redirect_stdout(io.StringIO()) as output:
                                self.window.command_Reload(None)
                            self.assertTrue(self.window.recovered)
                            self.assertFalse(self.window._config_failed)
                            self.assertEqual(output.getvalue(), strings.CONFIG_RELOADED + "\n")
                        finally:
                            self.window.destroy()

            def test_native_dynamic_import_reload_hooks(self):
                import importlib

                scripts = data / "scripts"
                package = scripts / "rc_native_dynamic"
                package.mkdir(parents=True)
                (package / "__init__.py").write_text('', encoding="utf-8")
                (package / "main.py").write_text(
                    'from importlib import import_module\n'
                    'def read():\n    return import_module(".leaf", __package__).VALUE\n', encoding="utf-8")
                leaf = package / "leaf.py"
                listing_source = package / "listing.py"
                leaf.write_text('VALUE = "old"\n', encoding="utf-8")
                listing_source.write_text('VALUE = "old-list"\n', encoding="utf-8")
                config = data / "custom.py"
                config.write_text(
                    'import importlib\ndef configure(window):\n'
                    '    value = importlib.import_module("rc_native_dynamic.main").read()\n'
                    '    window.keymap["C-F8"] = lambda info: value\n'
                    'def configure_ListWindow(window):\n'
                    '    value = importlib.import_module("rc_native_dynamic.listing").VALUE\n'
                    '    window.keymap["C-F8"] = lambda info: value\n', encoding="utf-8")
                import clnch_listwindow
                original_import = importlib.import_module
                with patch.object(sys, "path", [*sys.path, str(scripts)]), patch.dict(sys.modules):
                    old_listing = None
                    try:
                        for value, list_value in (("old", "old-list"), ("new", "new-list")):
                            with contextlib.redirect_stdout(io.StringIO()) as output:
                                self.window.command_Reload(None)
                            self.assertEqual(output.getvalue(), strings.CONFIG_RELOADED + "\n")
                            self.assertEqual(self.window.keymap["C-F8"](None), value)
                            self.assertNotIn("rc_native_dynamic.listing", sys.modules)
                            listing = clnch_listwindow.ListWindow(0, 0, 10, 1, 20, 4, self.window,
                                                                 show=False, title="Dynamic", items=["item"])
                            try:
                                self.assertEqual(listing.keymap["C-F8"](None), list_value)
                                if old_listing is None:
                                    old_listing = listing
                                    listing = None
                                else:
                                    self.assertEqual(old_listing.keymap["C-F8"](None), "old-list")
                            finally:
                                if listing is not None:
                                    listing.destroy()
                            leaf.write_text('VALUE = "new"\n', encoding="utf-8")
                            listing_source.write_text('VALUE = "new-list"\n', encoding="utf-8")
                        self.assertIs(importlib.import_module, original_import)
                    finally:
                        if old_listing is not None:
                            old_listing.destroy()

            def test_native_extension_reload_resources_and_failures(self):
                import gc
                import weakref

                import pyauto

                baseline_status = set(self.window.custom_status_bar_map)
                scripts = data / "scripts"
                scripts.mkdir(exist_ok=True)
                source = scripts / "rc_native_reload.py"
                helper = scripts / "rc_native_leaf.py"
                helper.write_text('VALUE = "old"\nDELETED = 1\n', encoding="utf-8")
                source.write_text(
                    'from rc_native_leaf import VALUE\n'
                    'import ckit, pyauto\n'
                    'def configure(window):\n'
                    '    child = ckit.TextWindow(show=False)\n'
                    '    window.registerConfigCleanup(child.destroy)\n'
                    '    window.reload_child = child.getHWND()\n'
                    '    hook = pyauto.Hook()\n'
                    '    window.registerConfigCleanup(hook.destroy)\n'
                    '    def tick():\n'
                    '        window.reload_ticks += 1\n'
                    '    window.reload_ticks = 0\n'
                    '    window.setTimer(tick, 10)\n'
                    '    window.registerConfigCleanup(lambda: window.killTimer(tick))\n'
                    '    def status(width):\n'
                    '        return VALUE\n'
                    '    window.registerStatusBar(status, interval=10)\n'
                    '    window.registerConfigCleanup(lambda: window.unregisterStatusBar(status))\n'
                    '    window.keymap["C-F8"] = lambda info: VALUE\n'
                    '    window.launcher.command_list.append(("reloadvalue", lambda info: VALUE))\n'
                    'def configure_list(window):\n'
                    '    window.keymap["C-F8"] = lambda info: VALUE\n', encoding="utf-8")
                config = data / "custom.py"
                text = ('import importlib\nrc_native_reload = importlib.import_module("rc_native_reload")\n'
                        'def configure(window):\n'
                        '    rc_native_reload.configure(window)\n'
                        'def configure_ListWindow(window):\n'
                        '    rc_native_reload.configure_list(window)\n')
                user32.IsWindow.argtypes = (wintypes.HWND,)
                with patch.object(sys, "path", [*sys.path, str(scripts)]), patch.dict(sys.modules):
                    config.write_text(text, encoding="utf-8")
                    self.window.configure()
                    self.pump(lambda: self.window.reload_ticks >= 2)
                    previous = self.window.custom
                    child = self.window.reload_child
                    leaf = weakref.ref(sys.modules["rc_native_leaf"])
                    key = weakref.ref(self.window.keymap["C-F8"])
                    for source in ('bad syntax !!!', 'raise SystemExit("load exit")\n',
                                   'raise KeyboardInterrupt("load interrupt")\n'):
                        helper.write_text(source, encoding="utf-8")
                        with redirect_stderr(io.StringIO()):
                            self.window.configure()
                        self.assertIs(self.window.custom, previous)
                        self.assertTrue(user32.IsWindow(child))
                        self.assertEqual(self.window.keymap["C-F8"](None), "old")
                    helper.write_text('VALUE = "new"\n', encoding="utf-8")
                    config.write_text(text + 'configure_ListWindow = None\n', encoding="utf-8")
                    with redirect_stderr(io.StringIO()) as errors:
                        self.window.configure()
                    self.assertIn("custom.configure_ListWindow must be callable", errors.getvalue())
                    self.assertIs(self.window.custom, previous)
                    self.assertTrue(user32.IsWindow(child))
                    self.assertEqual(self.window.keymap["C-F8"](None), "old")
                    config.write_text(text, encoding="utf-8")
                    helper.write_text('VALUE = "new"\n', encoding="utf-8")
                    for _ in range(3):
                        self.window.configure()
                        self.assertFalse(user32.IsWindow(child))
                        child = self.window.reload_child
                        self.assertEqual(self.window.keymap["C-F8"](None), "new")
                        self.assertEqual(dict(self.window.launcher.command_list)["reloadvalue"](None), "new")
                        self.assertEqual([name for name, _ in self.window.launcher.command_list].count("reloadvalue"), 1)
                        self.assertFalse(hasattr(sys.modules["rc_native_leaf"], "DELETED"))
                        import clnch_listwindow
                        listing = clnch_listwindow.ListWindow(0, 0, 10, 1, 20, 4, self.window,
                                                             show=False, title="Test", items=["item"])
                        try:
                            self.assertEqual(listing.keymap["C-F8"](None), "new")
                        finally:
                            listing.destroy()
                    del previous
                    gc.collect()
                    self.assertIsNone(leaf())
                    self.assertIsNone(key())
                    config.write_text("", encoding="utf-8")
                    self.window.configure()
                    self.assertFalse(user32.IsWindow(child))
                    self.assertNotIn("reloadvalue", dict(self.window.launcher.command_list))
                    self.assertNotIn("rc_native_reload", sys.modules)
                    ticks = self.window.reload_ticks
                    deadline = time.monotonic() + 0.08
                    self.pump(lambda: time.monotonic() >= deadline)
                    self.assertEqual(self.window.reload_ticks, ticks)
                    self.assertEqual(set(self.window.custom_status_bar_map), baseline_status)
                    hook = pyauto.Hook()
                    hook.destroy()
                    from test_extension_examples import example_sources
                    config.write_text(example_sources()["reload_cleanup"], encoding="utf-8")
                    self.window.configure()
                    self.assertEqual(len(self.window.custom_status_bar_map), len(baseline_status) + 1)
                    config.write_text("", encoding="utf-8")
                    self.window.configure()
                    self.assertEqual(set(self.window.custom_status_bar_map), baseline_status)
                    # Actual MainWindow shutdown runs the same cleanup path.
                    config.write_text(text, encoding="utf-8")
                    self.window.configure()
                    child = self.window.reload_child
                    def fail_cleanup():
                        raise SystemExit("shutdown exit")
                    self.window.registerConfigCleanup(fail_cleanup)
                    with redirect_stderr(io.StringIO()) as errors:
                        self.assertTrue(self.doCleanups())
                    self.assertIn("SystemExit: shutdown exit", errors.getvalue())
                    self.assertFalse(user32.IsWindow(child))
                    hook = pyauto.Hook()
                    hook.destroy()

            def test_native_partial_cleanup_disables_released_resource_callbacks(self):
                import clnch_listwindow

                scripts = data / "scripts"
                scripts.mkdir(exist_ok=True)
                (scripts / "rc_partial_cleanup.py").write_text(
                    'import ckit\n'
                    'blocked = True\n'
                    'attempts = 0\n'
                    'def configure(window):\n'
                    '    global child\n'
                    '    child = ckit.TextWindow(show=False)\n'
                    '    window.partial_child = child.getHWND()\n'
                    '    def wait():\n'
                    '        global attempts\n'
                    '        attempts += 1\n'
                    '        if blocked: raise RuntimeError("cleanup pending")\n'
                    '    window.registerConfigCleanup(wait)\n'
                    '    def release():\n'
                    '        child.destroy()\n'
                    '        window.partial_releases += 1\n'
                    '    window.registerConfigCleanup(release)\n'
                    '    window.keymap["C-F8"] = use\n'
                    '    window.launcher.command_list.append(("partialuse", use))\n'
                    '    def tick():\n'
                    '        use(None)\n'
                    '    window.setTimer(tick, 10)\n'
                    '    window.registerConfigCleanup(lambda: window.killTimer(tick))\n'
                    '    def status(width):\n'
                    '        return use(None)\n'
                    '    window.registerStatusBar(status, interval=10)\n'
                    '    window.registerConfigCleanup(lambda: window.unregisterStatusBar(status))\n'
                    'def use(info):\n'
                    '    child.getWindowRect()\n'
                    '    return "resource alive"\n', encoding="utf-8")
                config = data / "custom.py"
                text = ('import rc_partial_cleanup\n'
                        'def configure(window):\n    rc_partial_cleanup.configure(window)\n'
                        'def configure_ListWindow(window):\n    rc_partial_cleanup.use(None)\n')
                self.window.partial_releases = 0
                (data / "commands.json").write_text(
                    '{"fallback": {"target": {"link": "about"}}}', encoding="utf-8")
                baseline_status = set(self.window.custom_status_bar_map)
                user32.IsWindow.argtypes = (wintypes.HWND,)
                with patch.object(sys, "path", [*sys.path, str(scripts)]), patch.dict(sys.modules):
                    config.write_text(text, encoding="utf-8")
                    self.window.configure()
                    previous = self.window.custom
                    module = sys.modules["rc_partial_cleanup"]
                    child = self.window.partial_child
                    old_key = self.window.keymap["C-F8"]
                    old_command = dict(self.window.launcher.command_list)["partialuse"]
                    config.write_text('raise RuntimeError("loading failed")\n', encoding="utf-8")
                    with redirect_stderr(io.StringIO()) as errors:
                        self.window.command_Reload(None)
                    self.assertIn("loading failed", errors.getvalue())
                    self.assertIs(self.window.custom, previous)
                    self.assertTrue(user32.IsWindow(child))
                    self.assertEqual(old_key(None), "resource alive")
                    self.assertEqual(module.attempts, 0)
                    self.assertEqual(self.window.partial_releases, 0)
                    config.write_text(text, encoding="utf-8")

                    def reload_while_typing():
                        edit = self.window.commandline_edit
                        with redirect_stderr(io.StringIO()) as errors, \
                                contextlib.redirect_stdout(io.StringIO()) as output:
                            self.window.command_Reload(None)
                        self.assertIn("cleanup pending", errors.getvalue())
                        self.assertEqual(output.getvalue(), "")
                        self.assertTrue(self.window._config_failed)
                        self.assertFalse(user32.IsWindow(child))
                        # External old references remain invalid; active registrations must be removed.
                        for callback in (old_key, old_command, previous.configure_ListWindow):
                            with self.assertRaisesRegex(ValueError, "already destroyed"):
                                callback(None)
                        with self.assertRaises(KeyError):
                            self.window.keymap["C-F8"]
                        self.assertNotIn("partialuse", dict(self.window.launcher.command_list))
                        with redirect_stderr(io.StringIO()) as dispatch_errors:
                            self.key(ckit.VK_F8, 2)
                        self.assertEqual(dispatch_errors.getvalue(), "")
                        self.assertIs(self.window.commandline_edit, edit)
                        self.assertEqual(edit.getText(), "keep input")
                    self.input_action("keep input", reload_while_typing)
                    self.assertIsNone(self.window.custom)
                    self.assertTrue({"config", "reload", "quit", "new", "fallback"}
                                    <= dict(self.window.launcher.command_list).keys())
                    self.assertEqual(ckit.ckit_userconfig.user_namespace, {})
                    self.assertIs(sys.modules["custom"], previous)
                    self.assertIs(sys.modules["rc_partial_cleanup"], module)
                    self.assertEqual(module.attempts, 1)
                    self.assertEqual(self.window.partial_releases, 1)
                    self.assertEqual(len(self.window._config_cleanup), 1)
                    self.assertEqual(set(self.window.custom_status_bar_map), baseline_status)
                    listing = clnch_listwindow.ListWindow(0, 0, 10, 1, 20, 4, self.window,
                                                         show=False, title="Recovery", items=["item"])
                    listing.destroy()
                    with redirect_stderr(io.StringIO()) as errors:
                        self.window.command_Reload(None)
                    self.assertIn("cleanup pending", errors.getvalue())
                    self.assertEqual(module.attempts, 2)
                    self.assertEqual(self.window.partial_releases, 1)
                    module.blocked = False
                    with contextlib.redirect_stdout(io.StringIO()) as output:
                        self.window.command_Reload(None)
                    self.assertEqual(output.getvalue(), strings.CONFIG_RELOADED + "\n")
                    self.assertEqual(module.attempts, 3)
                    self.assertEqual(self.window.partial_releases, 1)
                    self.assertFalse(self.window._config_failed)
                    self.assertIsNot(sys.modules["rc_partial_cleanup"], module)
                    self.assertEqual(self.window.keymap["C-F8"](None), "resource alive")
                    # Shutdown releases the newly acquired resource even when its wait callback fails.
                    with redirect_stderr(io.StringIO()) as errors:
                        self.assertTrue(self.doCleanups())
                    self.assertIn("cleanup pending", errors.getvalue())
                    self.assertEqual(self.window.partial_releases, 2)
                    self.assertFalse(user32.IsWindow(self.window.partial_child))

            def test_native_partial_cleanup_retained_timer_requires_owner_stop(self):
                child = ckit.TextWindow(show=False)
                blocked = True
                failures = []
                def tick():
                    try:
                        child.getWindowRect()
                    except ValueError as error:
                        failures.append(str(error))
                self.window.setTimer(tick, 10)
                self.addCleanup(self.window.killTimer, tick)
                def stop():
                    if blocked:
                        raise RuntimeError("timer owner pending")
                    self.window.killTimer(tick)
                self.window.registerConfigCleanup(stop)
                self.window.registerConfigCleanup(child.destroy)
                with redirect_stderr(io.StringIO()) as errors:
                    self.window.command_Reload(None)
                self.assertIn("timer owner pending", errors.getvalue())
                self.assertIsNone(self.window.custom)
                self.assertEqual(self.window._config_cleanup, [stop])
                # Arbitrary registered timers still run if their owner failed before stopping them.
                self.pump(lambda: bool(failures))
                self.assertEqual(set(failures), {"already destroyed."})
                blocked = False
                with redirect_stderr(io.StringIO()) as errors:
                    self.window.command_Reload(None)
                self.assertEqual(errors.getvalue(), "")
                self.assertFalse(self.window._config_failed)
                self.assertEqual(self.window._config_cleanup, [])
                count = len(failures)
                deadline = time.monotonic() + 0.05
                self.pump(lambda: time.monotonic() >= deadline)
                self.assertEqual(len(failures), count)

            def test_native_extension_reload_waits_for_documented_job(self):
                from test_extension_examples import example_sources

                scripts = data / "scripts"
                scripts.mkdir(exist_ok=True)
                sources = example_sources()
                (scripts / "my_job.py").write_text(sources["job_module"], encoding="utf-8")
                config = data / "custom.py"
                config.write_text(sources["job_setup"], encoding="utf-8")
                with patch.object(sys, "path", [*sys.path, str(scripts)]), patch.dict(sys.modules):
                    sys.modules.pop("my_job", None)
                    self.window.configure()
                    self.invoke("myjob")
                    module = sys.modules["my_job"]
                    item = module._active
                    previous = self.window.custom
                    config.write_text("", encoding="utf-8")
                    with redirect_stderr(io.StringIO()):
                        self.window.configure()
                    self.assertIsNone(self.window.custom)
                    self.assertIs(sys.modules["custom"], previous)
                    self.assertNotIn("myjob", dict(self.window.launcher.command_list))
                    self.assertIs(sys.modules["my_job"], module)
                    self.assertTrue(item.isCanceled())
                    self.pump(lambda: module._active is None)
                    self.window.configure()
                    self.assertIsNot(self.window.custom, previous)
                    self.assertNotIn("myjob", dict(self.window.launcher.command_list))
                    self.assertNotIn("my_job", sys.modules)

            def test_native_launcher_reload_uses_live_keymaps_and_providers(self):
                clnch_ini.set("INPUT", "history_mode", "session")
                clnch_ini.set("INPUT", "clear_on_deactivate", "0")
                self.window.configure()
                original = (data / "custom.py").read_text(encoding="utf-8")
                (data / "custom.py").write_text(original +
                    '    window.keymap["C-F8"] = lambda info: "after reload"\n', encoding="utf-8")
                self.window.keymap["C-R"] = self.window.command.Reload
                def action():
                    edit = self.window.commandline_edit
                    self.key(82, 2)
                    self.assertIs(self.window.commandline_edit, edit)
                    self.assertEqual(edit.getText(), "keep input")
                    self.assertEqual(self.window.commandline_history, [])
                    self.key(ckit.VK_F8, 2)
                    self.assertEqual(edit.getText(), "after reload")
                    self.assertEqual(edit.getSelection(), [0, 12])
                    edit.setText("customonly;日本語")
                    self.key(ckit.VK_RETURN)
                self.input_action("keep input", action)
                self.assertEqual(self.window.custom_runs, 3)
                self.assertEqual(self.window.custom_args, ["日本語"])
                self.assertEqual(self.window.commandline_history, ["customonly;日本語"])

            def test_native_status_layer_timers_and_message_replacement(self):
                draws = []
                def status(width):
                    draws.append(width)
                    return "status"
                self.window.registerStatusBar(status, priority=-2, interval=10)
                try:
                    self.pump(lambda: bool(draws))
                    self.window.setStatusMessage("old", timeout=20)
                    self.window.setStatusMessage("new")
                    deadline = time.monotonic() + 0.1
                    self.pump(lambda: time.monotonic() >= deadline)
                    self.assertTrue(self.window.simple_status_bar_resistered)
                    self.assertEqual(self.window.simple_status_bar_layer.message, "new")
                    self.window.clearStatusMessage()
                    self.window.clearStatusMessage()
                    self.window.setStatusMessage("expires", timeout=20)
                    self.pump(lambda: not self.window.simple_status_bar_resistered)
                finally:
                    self.window.unregisterStatusBar(status)
                count = len(draws)
                deadline = time.monotonic() + 0.05
                self.pump(lambda: time.monotonic() >= deadline)
                self.assertEqual(len(draws), count)
                self.assertNotIn(status, self.window.custom_status_bar_map)

            def test_native_history_empty_delete_selection_and_failure_cleanup(self):
                import clnch_listwindow
                original = clnch_listwindow.ListWindow
                handles, launches = [], []
                user32.IsWindow.argtypes = (wintypes.HWND,)
                test = self
                for mode in ("empty", "select", "failure"):
                    with self.subTest(mode=mode):
                        self.window.commandline_history = [] if mode == "empty" else ["first", "日本語"]
                        class HistoryList(original):
                            def messageLoop(self, mode=mode):
                                handles.append(self.getHWND())
                                test.assertFalse(test.window.isEnabled())
                                if mode == "failure":
                                    raise RuntimeError("history loop")
                                test.key(ckit.VK_DELETE, window=self)
                                test.key(ckit.VK_ESCAPE if mode == "empty" else ckit.VK_RETURN, window=self)
                        with patch.object(clnch_listwindow, "ListWindow", HistoryList), \
                             patch.object(self.window, "activeMessageLoop", side_effect=lambda *args: launches.append(args)):
                            if mode == "failure":
                                with self.assertRaisesRegex(RuntimeError, "history loop"):
                                    self.window.command_History(None)
                            else:
                                self.window.command_History(None)
                        self.assertTrue(self.window.isEnabled())
                        self.assertFalse(user32.IsWindow(handles[-1]))
                self.assertEqual(launches, [("日本語", [0, 3])])

            def test_native_input_text_selection_candidates_and_reentry(self):
                captured = []
                def edit():
                    line = self.window.keydown_hook.__self__
                    line.setSelection([0, len(line.getText())])
                    user32.SendMessageW(self.window.getHWND(), 0x0102, ord("語"), 1)
                    captured.append((line.getText(), line.getSelection()))
                    self.assertIsNotNone(self.window.commandline_edit.list_window)
                    self.key(ckit.VK_ESCAPE)
                    self.assertEqual(line.getText(), "")
                self.input_action("日本語 draft", edit)
                self.assertEqual(captured, [("語", [1, 1])])
                self.input_action("second", lambda: self.key(ckit.VK_RETURN))
                self.assertIsNone(self.window.char_hook)
                self.assertFalse(self.window.mouse_event_mask)
                self.assertIsNone(self.window.status_bar_paint_hook)

            def test_native_commandline_edit_reacquisition_and_history_removal(self):
                target = data / "context target.txt"
                target.write_text("context")
                info = SimpleNamespace(args=[str(target)])
                self.assertIsNone(self.window.commandline_edit)
                for command, attribute in ((self.window.command_ContextMenu, "closeList"),
                                           (self.window.command_RemoveHistory, "removeCandidate")):
                    with self.assertRaises(AttributeError) as caught:
                        command(info)
                    self.assertEqual(str(caught.exception), f"'NoneType' object has no attribute '{attribute}'")
                    self.assertEqual(caught.exception.name, attribute)
                    self.assertIsNone(caught.exception.obj)
                for replacing in (False, True):
                    def context(replacing=replacing):
                        original = self.window.commandline_edit
                        assert original is not None
                        replacement = ckit.EditWidget(self.window, 3, 0, 17, 1, "replacement") if replacing else original
                        close_list = original.closeList
                        def close():
                            close_list()
                            if replacing:
                                self.window.commandline_edit = replacement
                        try:
                            expected = self.window.charToScreen(replacement.x + replacement.width, 1)
                            with patch.object(original, "closeList", close), \
                                 patch.object(clnch_mainwindow.clnch_native, "popupContextMenu") as shell:
                                self.window.command_ContextMenu(info)
                            shell.assert_called_once_with(self.window.getHWND(), expected[0], expected[1],
                                                          str(target.parent), [target.name])
                            self.assertIs(self.window.commandline_edit, replacement)
                            self.assertFalse(original.isListOpened())
                        finally:
                            self.window.commandline_edit = original
                            if replacing:
                                replacement.destroy()
                    self.input_action(str(target), context)
                self.window.input_settings.update(HISTORY_MODE="session", COMPLETION_MODE="standard")
                self.window.commandline_history = ["remove-me"]
                def remove_history():
                    original = self.window.commandline_edit
                    assert original is not None
                    original.closeList()
                    self.key(ckit.VK_K, ckit.MODKEY_CTRL)
                    self.assertEqual(self.window.commandline_history, [])
                    self.assertEqual(original.getText(), "")
                    self.assertIs(self.window.commandline_edit, original)
                self.input_action("remove-me", remove_history)

            def test_native_input_initialization_and_loop_failure_cleanup(self):
                for stage in ("makeVisible", "setImeRect", "messageLoop", "destroy"):
                    with self.subTest(stage=stage):
                        target = self.window if stage == "messageLoop" else ckit.EditWidget
                        original_destroy = ckit.EditWidget.destroy
                        destroyed = []
                        def destroy(edit, stage=stage, original_destroy=original_destroy, destroyed=destroyed):
                            original_destroy(edit)
                            destroyed.append(edit)
                            if stage == "destroy":
                                raise RuntimeError("destroy")
                        with patch.object(ckit.EditWidget, "destroy", destroy):
                            if stage == "destroy":
                                with patch.object(self.window, "messageLoop"), self.assertRaisesRegex(RuntimeError, stage):
                                    self.window.commandLine("", candidate_handler=lambda info: (["candidate"], 0))
                            else:
                                with patch.object(target, stage, side_effect=RuntimeError(stage)), \
                                     self.assertRaisesRegex(RuntimeError, stage):
                                    self.window.commandLine("", candidate_handler=lambda info: (["candidate"], 0))
                        self.assertEqual(len(destroyed), 1)
                        self.assertIsNone(self.window.commandline_edit)
                        self.assertIsNone(self.window.keydown_hook)
                        self.assertIsNone(self.window.char_hook)
                        self.assertFalse(self.window.mouse_event_mask)
                        self.assertIsNone(self.window.status_bar_paint_hook)
                        self.input_action("recovered", lambda: self.key(ckit.VK_ESCAPE))

            def test_native_top_level_deferred_string_without_input(self):
                self.window.input_settings["HISTORY_MODE"] = "session"
                original_destroy = ckit.EditWidget.destroy
                for result in ("returned text", "", None):
                    with self.subTest(result=result):
                        calls, destroyed = [], []
                        self.window.commandline_history = ["history sentinel"]
                        def destroy(edit, destroyed=destroyed):
                            original_destroy(edit)
                            destroyed.append(edit)
                        def command(info, calls=calls, destroyed=destroyed, result=result):
                            calls.append((list(info.args), info.mod, self.window.commandline_edit,
                                self.window.keydown_hook, self.window.char_hook,
                                self.window.mouse_event_mask, self.window.status_bar_paint_hook,
                                len(destroyed)))
                            return result
                        self.window.launcher.command_list.append(("return-probe", command))
                        output = io.StringIO()
                        try:
                            with patch.object(ckit.EditWidget, "destroy", destroy), patch("sys.stdout", output):
                                self.input_action("return-probe;日本語", lambda: self.key(ckit.VK_RETURN, 2))
                        finally:
                            self.window.launcher.command_list.pop()
                        self.assertEqual(output.getvalue(), "")
                        self.assertEqual(calls, [(["日本語"], 2, None, None, None, False, None, 1)])
                        self.assertEqual(len(destroyed), 1)
                        expected = ["history sentinel"] if isinstance(result, str) else ["return-probe;日本語", "history sentinel"]
                        self.assertEqual(self.window.commandline_history, expected)
                        self.assertIsNone(self.window.commandline_edit)
                        self.assertIsNone(self.window.keydown_hook)
                        self.assertIsNone(self.window.char_hook)
                        self.assertFalse(self.window.mouse_event_mask)
                        self.assertIsNone(self.window.status_bar_paint_hook)

            def test_native_nested_input_and_deferred_string_target(self):
                errors, results = [], []
                def outer():
                    self.window.killTimer(outer)
                    attached = self.window.commandline_edit
                    hooks = (self.window.keydown_hook, self.window.char_hook)
                    def inner():
                        self.window.killTimer(inner)
                        line = self.window.keydown_hook.__self__
                        line.planCommand(lambda info: "outer replacement", None, None)
                        self.key(ckit.VK_RETURN)
                    try:
                        self.window.setTimer(inner, 30)
                        results.append(self.window.commandLine("inner", "inner text"))
                        self.assertIs(self.window.commandline_edit, attached)
                        self.assertEqual((self.window.keydown_hook, self.window.char_hook), hooks)
                        self.assertEqual(attached.getText(), "outer replacement")
                        self.assertEqual(attached.getSelection(), [0, 17])
                    except BaseException as error:  # noqa: BLE001  # Surface native timer assertions after leaving the loop.
                        errors.append(error)
                    finally:
                        self.window.quit()
                self.window.setTimer(outer, 30)
                self.window.commandLine("outer", "outer text")
                self.assertEqual(errors, [])
                self.assertEqual(results, ["inner text"])
                self.assertIsNone(self.window.commandline_edit)

            def test_native_worker_cancel_pumps_ui_and_restores_outer_session(self):
                def action():
                    attached = self.window.commandline_edit
                    hooks = (self.window.keydown_hook, self.window.char_hook)
                    released, canceled = threading.Event(), threading.Event()
                    errors = []
                    def cancel(value):
                        self.assertEqual(value, "arg")
                        canceled.set()
                    def drive():
                        self.window.killTimer(drive)
                        try:
                            self.assertIs(self.window.commandline_edit, attached)
                            self.key(ckit.VK_ESCAPE)
                            self.assertTrue(canceled.is_set())
                            self.assertEqual(attached.getText(), "keep input")
                        except BaseException as error:  # noqa: BLE001  # Surface timer assertions and always release the worker.
                            errors.append(error)
                        finally:
                            released.set()
                    self.window.setTimer(drive, 30)
                    try:
                        self.assertTrue(self.window.subThreadCall(lambda: released.wait(3), (), cancel, ("arg",)))
                    finally:
                        released.set()
                    self.assertEqual(errors, [])
                    self.assertEqual((self.window.keydown_hook, self.window.char_hook), hooks)
                    user32.SendMessageW(self.window.getHWND(), 0x0102, ord("!"), 1)
                    self.assertEqual(attached.getText(), "keep input!")
                self.input_action("keep input", action)

            def test_native_subprocess_startup_and_running_cancel(self):
                from ckit import ckit_subprocess

                child = IPC_SENDER.split("class CopyData")[0] + '''
u.CreateWindowExW.argtypes = (w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID)
u.CreateWindowExW.restype = w.HWND
u.IsWindow.argtypes = (w.HWND,)
u.GetMessageW.argtypes = (ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT)
u.TranslateMessage.argtypes = (ctypes.POINTER(w.MSG),)
u.DispatchMessageW.argtypes = (ctypes.POINTER(w.MSG),)
u.DispatchMessageW.restype = ctypes.c_ssize_t
hwnd = u.CreateWindowExW(0, "STATIC", "SubProcess cancellation test", 0,
    0, 0, 100, 100, None, None, None, None)
if not hwnd:
    raise ctypes.WinError(ctypes.get_last_error())
wndproc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
u.SetWindowLongPtrW.argtypes = (w.HWND, ctypes.c_int, wndproc_type)
u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
u.CallWindowProcW.argtypes = (ctypes.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
u.CallWindowProcW.restype = ctypes.c_ssize_t
@wndproc_type
def wndproc(window, message, wp, lp):
    if message == 2:
        u.PostQuitMessage(0)
    return u.CallWindowProcW(previous, window, message, wp, lp)
previous = u.SetWindowLongPtrW(hwnd, -4, wndproc)
print("ready", flush=True)
close_output = sys.argv[2] == "eof"
if close_output:
    import os
    os.close(1)
    os.close(2)
msg = w.MSG()
while u.IsWindow(hwnd) and u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
    u.TranslateMessage(ctypes.byref(msg))
    u.DispatchMessageW(ctypes.byref(msg))
if not close_output:
    print("closed", flush=True)
'''
                real_popen = subprocess.Popen
                real_wait = real_popen.wait
                def check_cancel(during_startup, close_output=False):
                    ready, release = threading.Event(), threading.Event()
                    output, processes, errors = [], [], []
                    def write(text):
                        output.append(text)
                        if text == "ready\r\n" and not close_output:
                            ready.set()
                    task = ckit.SubProcess([str(pythonw), "-B", "-S", "-c", child,
                                            station_name.value, "eof" if close_output else "open"], stdout_write=write)
                    def wait(process, *args, **kwargs):
                        if close_output and process is task.p and not args and not kwargs:
                            ready.set()
                        return real_wait(process, *args, **kwargs)
                    def popen(*args, **kwargs):
                        # New threads otherwise use the station's default desktop.
                        self.assertTrue(user32.SetThreadDesktop(desktop_handles[2]))
                        process = real_popen(*args, **kwargs)
                        processes.append(process)
                        if during_startup:
                            self.assertEqual(process.stdout.readline(), b"ready\r\n")
                            ready.set()
                            self.assertTrue(release.wait(5))
                        return process
                    def abort():
                        release.set()
                        for process in processes:
                            if process.poll() is None:
                                process.kill()
                    def drive():
                        if not ready.is_set():
                            return
                        self.window.killTimer(drive)
                        try:
                            self.assertEqual(task.p is None, during_startup)
                            self.key(ckit.VK_ESCAPE)
                        except BaseException as error:  # noqa: BLE001  # Surface timer failures after worker cleanup.
                            errors.append(error)
                        finally:
                            release.set()
                    watchdog = threading.Timer(8, abort)
                    watchdog.start()
                    self.window.setTimer(drive, 10)
                    hooks = (self.window.keydown_hook, self.window.char_hook)
                    try:
                        with self.subTest(during_startup=during_startup, close_output=close_output), \
                             patch.object(real_popen, "wait", wait), \
                             patch.object(subprocess, "Popen", side_effect=popen), \
                             patch.object(ckit_subprocess.ckit_misc, "terminateProcess",
                                          wraps=ckit_subprocess.ckit_misc.terminateProcess) as terminate:
                            result = self.window.subThreadCall(task, (), task.cancel, raise_error=True)
                            self.assertEqual(result, 0, (output[:8], errors, terminate.call_args_list))
                            self.assertEqual(output, ["ready\r\n"] if close_output else
                                             ["closed\r\n"] if during_startup else ["ready\r\n", "closed\r\n"])
                            self.assertTrue(task.p.stdin.closed)
                            self.assertTrue(task.p.stdout.closed)
                            terminate.assert_called_once_with(task.p.pid)
                            task.cancel()
                            terminate.assert_called_once()
                            self.assertEqual(errors, [])
                            self.assertEqual((self.window.keydown_hook, self.window.char_hook), hooks)
                    finally:
                        self.window.killTimer(drive)
                        watchdog.cancel()
                        watchdog.join(2)
                        abort()
                        for process in processes:
                            process.wait(timeout=3)
                            process.stdin.close()
                            process.stdout.close()

                for during_startup in (True, False):
                    check_cancel(during_startup)
                check_cancel(False, close_output=True)

            def test_native_ra_input_delegates_runas(self):
                self.apply({"np": {"target": {"link": "notepad.exe"}}})
                self.assertIn("_ra", dict(self.window.launcher.command_list))
                self.assertNotIn("_elevate", dict(self.window.launcher.command_list))
                calls = []
                def shell_command(*args, **kwargs):
                    return lambda info: calls.append((args, list(info.args)))
                with patch.object(self.window, "ShellExecuteCommand", side_effect=shell_command):
                    self.input_action(r"_ra;np C:\work\report.txt", lambda: self.key(ckit.VK_RETURN))
                self.assertEqual(calls, [(("runas", "notepad.exe", "", "", "normal"),
                                          [r"C:\work\report.txt"])])

            def test_native_ra_cancel_is_silent_and_other_errors_are_reported(self):
                self.apply({"np": {"target": {"link": "notepad.exe"}},
                            "alias": {"target": {"link": "np"}}})
                self.window.input_settings["HISTORY_MODE"] = "session"
                console = self.window.console_window
                for text, code, silent in (("_ra;np", 1223, True), ("_ra;alias", 1223, True),
                                          ("_ra;cmd", 1223, True), ("_ra;np", 2, False),
                                          ("_ra;np", 5, False), ("np", 1223, False)):
                    with self.subTest(text=text, code=code):
                        console.clearLog()
                        console.show(False)
                        console.setAutoShow(True)
                        console.write("existing console text\n", auto_show=False)
                        before = list(console.log.log)
                        self.window.commandline_history = []
                        error = ctypes.WinError(code)
                        console.registerStdio()
                        try:
                            with (patch.object(clnch_mainwindow.pyauto, "shellExecute", side_effect=error) as shell,
                                  patch.object(console, "write", wraps=console.write) as written):
                                self.input_action(text, lambda: self.key(ckit.VK_RETURN))
                                self.pump(lambda silent=silent: ckit.JobQueue.defaultQueue().numItems() == 0
                                          and (silent or console.opened))
                                shell.assert_called_once()
                                self.assertEqual(shell.call_args.args[0], "runas" if text.startswith("_ra;") else None)
                                if silent:
                                    written.assert_not_called()
                                    self.assertEqual(console.log.log, before)
                                    self.assertFalse(console.auto_show_required)
                                    self.assertFalse(console.opened)
                                else:
                                    lines = "\n".join(console.log.log)
                                    self.assertEqual(lines.count(strings.EXECUTE_ERROR), 1)
                                    self.assertIn(str(error), lines)
                        finally:
                            console.unregisterStdio()
                        self.assertIsNone(self.window.commandline_edit)
                        self.assertEqual(self.window.commandline_history, [text])
                output = data / "after-uac-cancel.json"
                self.apply({"ok": {"target": self.probe_action(output)}})
                self.input_action("ok;recovered", lambda: self.key(ckit.VK_RETURN))
                self.assertEqual(self.result(output)["args"], ["recovered"])

            def test_native_alias_cycle_notification_and_recovery(self):
                self.apply({"循環a": {"target": {"link": "循環b"}},
                            "循環b": {"target": {"link": "循環a"}}})
                console = self.window.console_window
                console.registerStdio()
                try:
                    self.input_action("循環a", lambda: self.key(ckit.VK_RETURN))
                finally:
                    console.unregisterStdio()
                message = strings.COMMAND_ALIAS_CYCLE.format(path="循環a → 循環b → 循環a")
                self.assertEqual(console.log.log.count(message), 1)
                self.assertFalse(any("RecursionError" in line for line in console.log.log))
                ckit.setClipboardText("cycle clipboard sentinel")
                self.input_action("循環a", lambda: self.key(ckit.VK_F12))
                self.assertEqual(ckit.getClipboardText(), "cycle clipboard sentinel")
                output = data / "after-cycle.json"
                self.apply({"ok": {"target": self.probe_action(output)}})
                self.input_action("ok;復帰確認", lambda: self.key(ckit.VK_RETURN))
                self.assertEqual(self.result(output)["args"], ["復帰確認"])

            def test_native_relative_link_rejection_console_f12_and_recovery(self):
                import clnch_commandexecutor

                folder = data / "relative-target"
                folder.mkdir(exist_ok=True)
                (folder / "tool.exe").touch()
                self.window.modifier_settings.update(CTRL_ACTION="mapped_folder",
                    SOURCE_ROOTS=(str(data),), CTRL_DESTINATION_ROOT=str(data))
                console = self.window.console_window
                for link in ("relative-target/tool.exe", r".\relative-target\tool.exe", "../folder",
                             r"\relative-target\tool.exe", "C:tool.exe", "%RECRAFT_RELATIVE%/tool.exe"):
                    self.apply({"origin": {"target": {"link": "middle", "workdir": str(data)}},
                                "middle": {"target": {"link": "child"}},
                                "child": {"target": {"link": link}}})
                    original = (data / "commands.json").read_bytes()
                    for mod in (0, ckit.MODKEY_SHIFT, ckit.MODKEY_CTRL):
                        with self.subTest(link=link, mod=mod):
                            console.clearLog()
                            console.show(False)
                            console.setAutoShow(True)
                            console.registerStdio()
                            try:
                                with (contextlib.chdir(data), patch.dict(os.environ, RECRAFT_RELATIVE="relative-target"),
                                      patch.object(clnch_mainwindow.pyauto, "shellExecute") as shell,
                                      patch.object(clnch_commandexecutor, "shellExecute") as opened):
                                    self.input_action("origin", lambda mod=mod: self.key(ckit.VK_RETURN, mod))
                                    self.pump(lambda: console.opened and ckit.JobQueue.defaultQueue().numItems() == 0)
                                    shell.assert_not_called()
                                    opened.assert_not_called()
                            finally:
                                console.unregisterStdio()
                            lines = console.log.log
                            self.assertEqual(sum("Link:" in line for line in lines), 1)
                            self.assertIn("origin", "\n".join(lines))
                            self.assertIsNone(self.window.commandline_edit)
                            self.assertEqual((data / "commands.json").read_bytes(), original)
                    console.clearLog()
                    before_copy = list(console.log.log)
                    self.input_action("origin", lambda: self.key(ckit.VK_F12))
                    self.assertEqual(ckit.getClipboardText(), link)
                    self.assertEqual(console.log.log, before_copy)
                output = data / "after-relative-error.json"
                self.apply({"ok": {"target": self.probe_action(output),
                                    "on_ctrl": {"link": "tools/invalid.exe"}}})
                self.input_action("ok;../document.txt", lambda: self.key(ckit.VK_RETURN))
                self.assertEqual(self.result(output)["args"], ["../document.txt"])

            def test_native_editor_relative_link_warning_preserves_edit_and_file(self):
                self.apply({"other": {"target": {"link": "tools/other.exe"}}})
                before = (data / "commands.json").read_bytes()
                def edit(editor):
                    editor.edit_by_id["name"].setText("saved")
                    editor.edit_by_id["link"].setText("tools/tool.exe")
                    messages = []
                    with patch.object(editor, "_show_error", side_effect=lambda *args: messages.append(args)):
                        self.assertFalse(editor._save())
                    self.assertEqual(messages, [(strings.ERROR_INPUT_TITLE,
                        strings.COMMAND_RELATIVE_LINK_GUI)])
                    self.assertEqual((data / "commands.json").read_bytes(), before)
                    self.assertEqual(editor.edit_by_id["link"].getText(), "tools/tool.exe")
                    self.assertFalse(editor.result_saved)
                    editor.edit_by_id["link"].setText("notepad.exe")
                    self.assertTrue(editor._save())
                self.assertEqual(self.run_editor(edit), "saved")
                self.assertEqual(clnch_cmdstore.load_commands(data / "commands.json")["other"]["target"]["link"],
                                 "tools/other.exe")

            def test_native_modifier_enter_and_live_settings(self):
                for modifier, key_mod in (("target", 0), ("on_ctrl", 2),
                                          ("on_shift", 4), ("on_ctrl_shift", 6)):
                    with self.subTest(modifier=modifier):
                        output = data / (modifier + ".json")
                        self.apply({"probe": {modifier: self.probe_action(output)}})
                        self.input_action("probe;日本語 input", lambda key_mod=key_mod: self.key(ckit.VK_RETURN, key_mod))
                        self.assertEqual(self.result(output)["args"], ["日本語 input"])
                output = data / "live-settings.json"
                self.apply({"probe": {"target": self.probe_action(output)}})
                handler = dict(self.window.launcher.command_list)["probe"]
                self.window.modifier_settings = {**self.window.modifier_settings, "CTRL_ACTION": "execute"}
                self.input_action("probe", lambda: self.key(ckit.VK_RETURN, 2))
                self.assertEqual(self.result(output)["args"], [])
                self.assertIs(dict(self.window.launcher.command_list)["probe"], handler)
                self.assertEqual(self.window.custom_runs, 1)

            @unittest.skipUnless(interactive_foreground, "Use --interactive-foreground for real foreground transitions")
            def test_native_external_launch_and_utility_foreground(self):
                import clnch_commandexecutor
                import clnch_standard

                import pyauto

                # Keep a real window in another process behind the launcher.
                source = PROBE.replace('output = Path(sys.argv[1])',
                    'result["hwnd"] = hwnd\n    output = Path(sys.argv[1])')
                source = source.replace('result = {"args":', 'u.SetForegroundWindow(hwnd)\n    result = {"args":')
                source = source.replace('finally:\n    u.DestroyWindow(hwnd)',
                    '    import time\n'
                    '    message = w.MSG()\n'
                    '    while not output.with_suffix(".stop").exists():\n'
                    '        u.AllowSetForegroundWindow(int(sys.argv[2]))\n'
                    '        while u.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):\n'
                    '            u.TranslateMessage(ctypes.byref(message))\n'
                    '            u.DispatchMessageW(ctypes.byref(message))\n'
                    '        time.sleep(0.01)\n'
                    'finally:\n    u.DestroyWindow(hwnd)')
                child_source = data / "foreground-child.py"
                child_source.write_text(source, encoding="utf-8")
                ready = data / "foreground-child.json"
                user32.GetForegroundWindow.restype = wintypes.HWND
                previous_foreground = user32.GetForegroundWindow()
                self.assertTrue(previous_foreground, "The current desktop cannot receive foreground activation")
                with subprocess.Popen([str(pythonw), "-B", "-S", str(child_source), str(ready), str(os.getpid())]) as child:
                    try:
                        self.pump(ready.exists)
                        child_hwnd = json.loads(ready.read_text(encoding="utf-8"))["hwnd"]
                        user32.IsWindow.argtypes = (wintypes.HWND,)
                        self.assertTrue(user32.IsWindow(child_hwnd))
                        self.window.show(True, False)
                        inactivate = self.enterContext(patch.object(self.window, "inactivate", wraps=self.window.inactivate))
                        self.apply({"probe": {"target": {"link": str(probe)}},
                                    "bad": {"target": {"link": str(data / "missing.exe")}}})

                        def activate():
                            def request():
                                if not self.window.isForeground():
                                    self.window.foreground()
                                return self.window.isForeground()
                            self.pump(request, timeout=2)
                            self.window.activate()

                        def jobs_finished():
                            self.pump(lambda: ckit.JobQueue.defaultQueue().numItems() == 0)

                        def released():
                            self.pump(lambda: bool(user32.GetForegroundWindow()) and not self.window.isForeground())

                        # A minimized launch must not add our own foreground change.
                        output = data / "foreground-launch.json"
                        self.apply({"probe": {"target": self.probe_action(output, view_mode="minimized")},
                                    "alias": {"target": {"link": "probe"}},
                                    "bad": {"target": {"link": str(data / "missing.exe")}}})
                        activate()
                        self.input_action("probe;日本語", lambda: self.key(ckit.VK_RETURN))
                        self.assertEqual(self.result(output)["args"], ["日本語"])
                        jobs_finished()
                        inactivate.assert_not_called()

                        for route in ("normal", "alias", "elevate", "modifier", "system", "file", "url",
                                      "alt_application", "alt_web", "alt_properties"):
                            for fails in (False, True):
                                with self.subTest(route=route, fails=fails):
                                    activate()
                                    text, mod = "probe", 0
                                    if route == "alias":
                                        text = "alias"
                                    elif route == "elevate":
                                        text = "_ra;probe"
                                    elif route == "modifier":
                                        mod = 4
                                    elif route == "system":
                                        text = "cmd.exe;/c echo test"
                                    elif route == "file":
                                        text = str(probe)
                                    elif route == "url":
                                        text = "https://example.org/"
                                    if route.startswith("alt_"):
                                        action = route.removeprefix("alt_")
                                        self.window.altenter_settings = {"action": action,
                                            "executable": str(pythonw), "arguments": "%param%",
                                            "url": "https://example.org/?q=%param%", "properties_first": False}
                                        text = str(probe) if action == "properties" else "日本語;two words"
                                        mod = 1
                                    with patch.object(pyauto, "shellExecute",
                                            side_effect=OSError("launch failure") if fails else None) as shell, patch.object(
                                            clnch_commandexecutor, "shellExecute", shell):
                                        self.input_action(text, lambda mod=mod: self.key(ckit.VK_RETURN, mod, system=bool(mod & 1)))
                                        jobs_finished()
                                        shell.assert_called_once()
                                    self.assertTrue(self.window.isForeground())
                                    inactivate.assert_not_called()

                        # Job completion leaves the next empty input editable when the target does not take focus.
                        activate()
                        with patch.object(pyauto, "shellExecute"):
                            self.input_action("probe", lambda: self.key(ckit.VK_RETURN))
                            def next_input():
                                jobs_finished()
                                self.assertTrue(self.window.isForeground())
                                self.assertEqual(self.window.commandline_edit.getText(), "")
                                inactivate.assert_not_called()
                            self.input_action("", next_input)

                        # A genuine OS rejection retains the existing empty input and console error.
                        activate()
                        self.input_action("bad", lambda: self.key(ckit.VK_RETURN))
                        jobs_finished()
                        self.assertTrue(self.window.isForeground())
                        def unknown():
                            edit = self.window.commandline_edit
                            self.key(ckit.VK_RETURN)
                            self.assertIs(self.window.commandline_edit, edit)
                            self.assertEqual(edit.getText(), "not_registered_98765")
                            self.assertTrue(self.window.isForeground())
                        self.input_action("not_registered_98765", unknown)

                        # A real launched application requests foreground itself, with no launcher handoff.
                        natural = data / "natural-foreground.json"
                        self.apply({"natural": {"target": {"link": str(pythonw), "args": subprocess.list2cmdline(
                            ["-B", "-S", str(child_source), str(natural), str(os.getpid())])}}})
                        activate()
                        try:
                            self.input_action("natural", lambda: self.key(ckit.VK_RETURN))
                            self.pump(natural.exists)
                            target_hwnd = json.loads(natural.read_text(encoding="utf-8"))["hwnd"]
                            self.pump(lambda: user32.GetForegroundWindow() == target_hwnd)
                            jobs_finished()
                            inactivate.assert_not_called()
                        finally:
                            natural.with_suffix(".stop").touch()
                            if natural.exists():
                                self.result(natural)

                        self.apply({"probe": {"target": {"link": str(probe)}}})
                        for outcome in ("success", "missing", "failure"):
                            activate()
                            inactivate.reset_mock()
                            with ExitStack() as stack:
                                # The isolated matrix tests the real clipboard; leave the user's clipboard untouched here.
                                stack.enter_context(patch.object(clnch_standard, "setClipboardText",
                                    side_effect=OSError("copy") if outcome == "failure" else None))
                                self.input_action("unknown" if outcome == "missing" else "probe",
                                    lambda: self.key(ckit.VK_F12))
                            released()
                            inactivate.assert_called_once_with()
                    finally:
                        ready.with_suffix(".stop").touch()
                        try:
                            child.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait(timeout=3)
                        user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
                        if user32.IsWindow(previous_foreground):
                            user32.SetForegroundWindow(previous_foreground)
                            self.pump(lambda: user32.GetForegroundWindow() == previous_foreground, timeout=2)

            def test_native_reload_menu_and_command_notifications(self):
                import clnch_standard
                config = data / "custom.py"
                commands = data / "commands.json"
                for route in ("command", "menu"):
                    for stage in ("json", "python", "cleanup", "standard", "custom", "success"):
                        with self.subTest(route=route, stage=stage):
                            self.window._config_cleanup.clear()
                            self.apply({})
                            config.write_text("", encoding="utf-8")
                            self.window.configure()
                            previous = self.window.custom
                            if stage == "json":
                                commands.write_text("{broken", encoding="utf-8")
                            elif stage == "python":
                                config.write_text("def broken(\n", encoding="utf-8")
                            elif stage == "cleanup":
                                def fail_cleanup():
                                    raise RuntimeError("cleanup failed")
                                self.window.registerConfigCleanup(fail_cleanup)
                            elif stage == "custom":
                                config.write_text('def configure(window):\n    raise RuntimeError("custom failed")\n',
                                                  encoding="utf-8")
                            standard = clnch_standard.configure
                            with patch.object(clnch_standard, "configure",
                                    side_effect=RuntimeError("standard failed") if stage == "standard" else standard), \
                                    contextlib.redirect_stdout(io.StringIO()) as output, \
                                    contextlib.redirect_stderr(io.StringIO()) as errors:
                                result = (self.window.command_Reload(None) if route == "command"
                                          else clnch_configmenu._reloadConfigFile(self.window))
                            self.assertIs(result, None if route == "command" else False)
                            self.assertEqual(output.getvalue().count(strings.CONFIG_RELOADED), int(stage == "success"))
                            self.assertEqual(bool(errors.getvalue()), stage != "success")
                            if stage in ("json", "python"):
                                self.assertIs(self.window.custom, previous)
                            else:
                                self.assertIsNot(self.window.custom, previous)

            def test_native_alt_enter_and_f12_key_dispatch(self):
                self.apply({"probe": {"target": {"link": str(probe)}}})
                import clnch_standard

                def dispatch_without_history(text, vk, mod=0, *, existing=False, disabled=False):
                    history = ["history sentinel"] + ([text] if existing else [])
                    self.window.commandline_history = history.copy()
                    clnch_ini.ini.remove_section("COMMANDLINE")
                    for i, entry in enumerate(history):
                        clnch_ini.set("COMMANDLINE", f"history_{i}", entry)
                    saved = clnch_ini.ini.items("COMMANDLINE")
                    def press():
                        with patch.object(self.window, "quit", wraps=self.window.quit) as quit_input:
                            edit = self.window.commandline_edit
                            selection = [2, 0] if disabled else [0, 0]
                            edit.setSelection(selection)
                            user32.SetFocus.argtypes = (wintypes.HWND,)
                            user32.GetFocus.restype = wintypes.HWND
                            user32.SetFocus(self.window.getHWND())
                            self.assertEqual(user32.GetFocus(), self.window.getHWND())
                            session = self.window.keydown_hook.__self__
                            with patch.object(clnch_mainwindow.pyauto, "shellExecute",
                                    wraps=clnch_mainwindow.pyauto.shellExecute) as shell, patch.object(
                                    self.window, "inactivate", wraps=self.window.inactivate) as inactivate:
                                self.key(vk, mod, system=bool(mod & 1))
                                if disabled:
                                    quit_input.assert_not_called()
                                    shell.assert_not_called()
                                    inactivate.assert_not_called()
                                    self.assertIs(self.window.commandline_edit, edit)
                                    self.assertIs(self.window.keydown_hook.__self__, session)
                                    self.assertEqual((edit.getText(), edit.getSelection()), (text, selection))
                                    self.assertEqual(user32.GetFocus(), self.window.getHWND())
                                else:
                                    quit_input.assert_called_once_with()
                    self.input_action(text, press)
                    self.assertEqual(self.window.commandline_history, history)
                    self.window.commandLineHistorySave()
                    self.assertEqual(clnch_ini.ini.items("COMMANDLINE"), saved)

                for mode in ("off", "session", "persistent"):
                    self.window.input_settings["HISTORY_MODE"] = mode
                    for key, binding_name, mod in (("", "A-Return", 1), ("ctrl", "C-A-Return", 3),
                                                    ("shift", "S-A-Return", 5), ("ctrl_shift", "C-S-A-Return", 7)):
                        for action in ("application", "none"):
                            with self.subTest(history=mode, key=key, alt_enter=action):
                                output = data / f"alt-enter-{mode}-{key}-{action}.json"
                                settings = {"action": action, "executable": str(pythonw),
                                    "arguments": subprocess.list2cmdline(["-B", "-S", str(probe), str(output)]) + " %param%",
                                    "url": "", "properties_first": False}
                                if key:
                                    del settings["properties_first"]
                                binding = self.window.cmd_keymap[binding_name]
                                clnch_configmenu._saveAltEnterSettings(self.window, key, **settings)
                                self.assertEqual(self.window.cmd_keymap[binding_name], binding)
                                dispatch_without_history("aaa" if action == "none" else "日本語;two words",
                                                         ckit.VK_RETURN, mod, existing=action == "none", disabled=action == "none")
                                if action == "application":
                                    self.assertEqual(self.result(output)["args"], ["日本語;two words"])
                                else:
                                    self.assertFalse(output.exists())
                                    self.assertEqual(ckit.JobQueue.defaultQueue().numItems(), 0)
                    for outcome in ("success", "missing", "failure"):
                        with self.subTest(history=mode, copy=outcome):
                            ckit.setClipboardText("clipboard sentinel")
                            text = "unknown;ignored" if outcome == "missing" else "probe;ignored"
                            with ExitStack() as stack:
                                if outcome == "failure":
                                    failed = stack.enter_context(patch.object(clnch_standard, "setClipboardText",
                                        side_effect=OSError("clipboard failure")))
                                dispatch_without_history(text, ckit.VK_F12, existing=outcome == "failure")
                                if outcome == "failure":
                                    failed.assert_called_once_with(str(probe))
                            self.assertEqual(ckit.getClipboardText(),
                                str(probe) if outcome == "success" else "clipboard sentinel")

            def test_native_alt_enter_key_selection_and_action_menus(self):
                import clnch_altenterconfig as config
                import clnch_listwindow

                plan = []
                for index, (key, (_section, label, _binding)) in enumerate(config.KEYS.items()):
                    plan.extend([
                        (strings.CONFIG_ALT_ENTER, max(index - 1, 0), index, 4),
                        (label, 0, 0, 1),
                        (label, 0, 2, 3 if key else 4),
                        (label, 0, -1, 2 if key else 3),
                    ])
                plan.append((strings.CONFIG_ALT_ENTER, 3, -1, 4))
                steps, frames = iter(plan), []
                original = clnch_listwindow.ListWindow

                def create(*args, **kwargs):
                    listing = original(*args, **kwargs)
                    listing.test_frame = (args[8], args[9])
                    return listing

                def drive(listing):
                    title, initial, selected, count = next(steps)
                    actual_title, items = listing.test_frame
                    self.assertEqual((actual_title, listing.select, len(items)), (title, initial, count))
                    self.assertFalse(self.window.isEnabled())
                    frames.append(items)
                    if selected < 0:
                        self.key(ckit.VK_ESCAPE, window=listing)
                    else:
                        self.key(ckit.VK_HOME, window=listing)
                        for _ in range(selected):
                            self.key(ckit.VK_DOWN, window=listing)
                        self.key(ckit.VK_RETURN, window=listing)

                with patch.object(clnch_listwindow, "ListWindow", side_effect=create), patch.object(
                        ckit.TextWindow, "messageLoop", drive):
                    clnch_configmenu._configAltEnter(self.window)
                self.assertEqual(len(frames), len(plan))
                for key in config.KEYS:
                    self.assertEqual(config.get_settings(self.window, key)["action"], "web")
                self.assertTrue(self.window.isEnabled())

            def test_native_alt_enter_settings_dialog_save_cancel_and_failure(self):
                import clnch_altenterconfig as config

                for key in config.KEYS:
                    with self.subTest(key=key):
                        clnch_configmenu._saveAltEnterSettings(self.window, key, action="application")
                        original = config.get_settings(self.window, key)
                        saved_bytes = Path(clnch_ini.ini_filename).read_bytes()
                        section = config.KEYS[key][0]
                        original_ini = dict(clnch_ini.ini.items(section))
                        attempts = []

                        def edit(dialog, key=key, attempts=attempts):
                            self.assertFalse(self.window.isEnabled())
                            fields = {item.id: item.widget for item in dialog.items if isinstance(item, ckit.Dialog.Edit)}
                            self.assertEqual(set(fields), {"executable", "arguments"})
                            if attempts:
                                self.assertEqual(fields["executable"].getText(), "tool-" + key + ".exe")
                                self.assertEqual(fields["arguments"].getText(), "--new %param%")
                                dialog.onKeyDown(ckit.VK_ESCAPE, 0)
                            else:
                                fields["executable"].setText("tool-" + key + ".exe")
                                fields["arguments"].setText("--new %param%")
                                dialog.onKeyDown(ckit.VK_RETURN, 0)
                            attempts.append(True)

                        # Actual atomic replacement failure keeps active settings and INI unchanged.
                        with patch.object(ckit.TextWindow, "messageLoop", edit), patch.object(
                                clnch_ini.os, "replace", side_effect=OSError("save failure")), contextlib.redirect_stdout(io.StringIO()):
                            clnch_configmenu._configAltEnterTarget(self.window, key)
                        self.assertEqual(len(attempts), 2)
                        self.assertIs(config.get_settings(self.window, key), original)
                        self.assertEqual(Path(clnch_ini.ini_filename).read_bytes(), saved_bytes)
                        self.assertEqual(dict(clnch_ini.ini.items(section)), original_ini)
                        self.assertTrue(self.window.isEnabled())

                        def cancel(dialog):
                            for item in dialog.items:
                                if isinstance(item, ckit.Dialog.Edit):
                                    item.widget.setText("cancelled")
                            dialog.onKeyDown(ckit.VK_ESCAPE, 0)
                        attempts.clear()
                        with patch.object(ckit.TextWindow, "messageLoop", cancel), patch.object(config, "write") as write:
                            clnch_configmenu._configAltEnterTarget(self.window, key)
                        write.assert_not_called()
                        self.assertIs(config.get_settings(self.window, key), original)
                        attempts.clear()
                        with patch.object(ckit.TextWindow, "messageLoop", edit):
                            clnch_configmenu._configAltEnterTarget(self.window, key)
                        current = config.get_settings(self.window, key)
                        self.assertEqual(current["executable"], "tool-" + key + ".exe")
                        self.assertEqual(config.read(clnch_ini, key), current)
                        with patch.object(clnch_ini, "write") as write:
                            clnch_configmenu._saveAltEnterSettings(self.window, key, **current)
                        write.assert_not_called()
                        self.assertTrue(self.window.isEnabled())

            def test_native_alt_enter_paths_web_and_no_fallback(self):
                import clnch_altenterconfig as config

                import pyauto
                targets = (("", 1), ("ctrl", 3), ("shift", 5), ("ctrl_shift", 7))
                for key, _mod in targets:
                    clnch_configmenu._saveAltEnterSettings(self.window, key, action="web",
                        url=f"https://example.org/{key}?q=%param%")
                path = str(probe)
                for key, mod in targets:
                    with self.subTest(key=key), patch.object(pyauto, "shellExecute") as shell:
                        self.input_action(path, lambda mod=mod: self.key(ckit.VK_RETURN, mod, system=True))
                        self.pump(lambda: shell.call_count == 1)
                        shell.assert_called_once_with(*config.build_action(config.get_settings(self.window, key), path, key))
                        if key:
                            self.assertIsNone(shell.call_args.args[0])
                        else:
                            self.assertEqual(shell.call_args.args[0], "properties")
                    # All other keys remain enabled, so a fallback would incorrectly end input.
                    clnch_configmenu._saveAltEnterSettings(self.window, key, action="none")
                    def disabled(mod=mod):
                        edit = self.window.commandline_edit
                        with patch.object(self.window, "quit") as quit_input:
                            self.key(ckit.VK_RETURN, mod, system=True)
                        quit_input.assert_not_called()
                        self.assertIs(self.window.commandline_edit, edit)
                    self.input_action(path, disabled)
                    clnch_configmenu._saveAltEnterSettings(self.window, key, action="web")

            def test_native_utility_key_overrides_and_other_command_history(self):
                self.window.input_settings["HISTORY_MODE"] = "persistent"
                config = data / "custom.py"
                config.write_text(
                    'def configure(window):\n'
                    '    def custom(info):\n'
                    '        window.custom_key_args = (info.args, info.mod)\n'
                    '    window.cmd_keymap["A-Return"] = custom\n'
                    '    window.cmd_keymap["C-A-Return"] = custom\n'
                    '    window.cmd_keymap["S-A-Return"] = custom\n'
                    '    window.cmd_keymap["C-S-A-Return"] = custom\n'
                    '    window.cmd_keymap["F12"] = custom\n', encoding="utf-8")
                self.window.configure()
                self.window.input_settings["HISTORY_MODE"] = "persistent"
                for vk, mod in ((ckit.VK_RETURN, 1), (ckit.VK_RETURN, 3), (ckit.VK_RETURN, 5),
                                (ckit.VK_RETURN, 7), (ckit.VK_F12, 0)):
                    self.window.commandline_history = ["history sentinel"]
                    self.input_action("custom;日本語;;", lambda vk=vk, mod=mod: self.key(vk, mod))
                    self.assertEqual(self.window.custom_key_args, (["custom;日本語;;"], 0))
                    self.assertEqual(self.window.commandline_history, ["custom;日本語;;", "history sentinel"])
                config.write_text("", encoding="utf-8")
                self.window.configure()
                self.window.input_settings["HISTORY_MODE"] = "persistent"
                self.window.commandline_history = ["history sentinel"]
                self.window.launcher.command_list.append(("named", lambda info: None))
                self.input_action("named;arg", lambda: self.key(ckit.VK_RETURN))
                self.assertEqual(self.window.commandline_history, ["named;arg", "history sentinel"])
                ui = self.window.cmd_keymap["F12"].__self__
                with patch.object(ui, "_open_command_editor", return_value=None) as editor:
                    self.input_action("named", lambda: self.key(ord("E"), 2))
                editor.assert_called_once_with("named")
                self.assertEqual(self.window.commandline_history, ["named", "named;arg", "history sentinel"])

            def test_native_completion_modes_exclude_history_files_and_providers(self):
                folder = data / "completion"
                folder.mkdir()
                (folder / "file.txt").touch()
                (folder / "folder").mkdir()
                self.window.launcher.command_list.extend([
                    ("candidate-name", lambda info: None), ("CANDIDATE-NAME", lambda info: None)])
                self.window.commandline_history = ["candidate-history", "CANDIDATE-NAME", str(folder / "file-history")]
                calls = []
                self.window.commandline_list.append(SimpleNamespace(
                    onCandidate=lambda info: calls.append(info.text) or ["candidate-custom", "CANDIDATE-CUSTOM"]))
                for enabled in (0, 1):
                    clnch_ini.set("MISC", "auto_complete", str(enabled))
                    for mode in ("off", "commands", "standard"):
                        with self.subTest(auto_complete=enabled, completion=mode):
                            self.window.input_settings["COMPLETION_MODE"] = mode
                            calls.clear()
                            def check_candidates(mode=mode, enabled=enabled):
                                edit = self.window.commandline_edit
                                info = ckit.EditWidget.UpdateInfo("candidate-", [10, 10])
                                expected = {"off": [], "commands": ["candidate-name"],
                                    "standard": ["candidate-history", "candidate-name", "candidate-custom"]}[mode] if enabled else []
                                self.assertEqual(edit.candidate_handler(info), (expected, 0))
                                text = str(folder) + "\\f"
                                with patch.object(clnch_mainwindow.clnch_native, "findFile",
                                                  wraps=clnch_mainwindow.clnch_native.findFile) as find:
                                    items, start = edit.candidate_handler(ckit.EditWidget.UpdateInfo(text, [len(text)] * 2))
                                if enabled and mode == "standard":
                                    directory = "folder" + ("/" if ckit.pathSlash() else "\\")
                                    self.assertEqual(items, ["file-history", directory, "file.txt", "candidate-custom"])
                                    self.assertEqual(start, len(text) - 1)
                                    find.assert_called_once()
                                else:
                                    self.assertEqual(items, [])
                                    find.assert_not_called()
                                self.key(ckit.VK_TAB)
                                self.assertEqual(edit.getText(), expected[0] if expected else "candidate-")
                                edit.setText("candidate")
                                edit.setSelection([9, 9])
                                user32.SendMessageW(self.window.getHWND(), 0x0102, ord("-"), 1)
                                self.assertEqual(edit.getText(), expected[0] if expected else "candidate-")
                                self.assertEqual(bool(edit.isListOpened()), bool(expected))
                                if not expected:
                                    before = (edit.getText(), edit.getSelection())
                                    for vk, mod in ((ckit.VK_TAB, 0), (ckit.VK_UP, 0), (ckit.VK_DOWN, 0),
                                                    (ckit.VK_PRIOR, 0), (ckit.VK_NEXT, 0), (ckit.VK_SPACE, 4)):
                                        self.key(vk, mod)
                                        self.assertEqual((edit.getText(), edit.getSelection()), before)
                                        self.assertFalse(edit.isListOpened())
                            self.input_action("candidate-", check_candidates)
                            self.assertEqual(bool(calls), bool(enabled and mode == "standard"))

            def test_native_auto_complete_runtime_switch_closes_candidates_and_keeps_execution(self):
                self.window.applyInputSettings(dict(self.window.input_settings,
                    HISTORY_MODE="session", SPACE_ACTION="complete"))
                executed = []
                self.window.launcher.command_list.append(("runtime-name", lambda info: executed.append(info.arg_string)))
                self.window.keymap["F6"] = self.window.command.AutoCompleteOn
                self.window.keymap["F7"] = self.window.command.AutoCompleteOff
                self.window.keymap["A-Space"] = self.window.command.AutoCompleteToggle
                raw = 'runtime-name;  "a  b"  '
                for initial in (0, 1):
                    clnch_ini.set("MISC", "auto_complete", str(initial))
                    for mode in ("off", "commands", "standard"):
                        with self.subTest(initial=initial, completion=mode):
                            self.window.input_settings["COMPLETION_MODE"] = mode
                            self.window.commandline_history = ["runtime-history"]
                            def switch(mode=mode, initial=initial):
                                edit = self.window.commandline_edit
                                self.assertEqual(edit.getAutoComplete(), initial)
                                self.key(ckit.VK_F6)
                                self.assertTrue(edit.getAutoComplete())
                                self.key(ckit.VK_TAB)
                                self.assertEqual(bool(edit.isListOpened()), mode != "off")
                                before = (edit.getText(), edit.getSelection())
                                self.key(ckit.VK_F7)
                                self.assertFalse(edit.getAutoComplete())
                                self.assertFalse(edit.isListOpened())
                                self.assertEqual((edit.getText(), edit.getSelection()), before)
                                edit.setText("runtime-")
                                edit.setSelection([8, 8])
                                for vk, mod in ((ckit.VK_TAB, 0), (ckit.VK_SPACE, 0), (ckit.VK_SPACE, 4),
                                                (ckit.VK_UP, 0), (ckit.VK_DOWN, 0)):
                                    self.key(vk, mod)
                                    self.assertEqual(edit.getText(), "runtime-")
                                    self.assertFalse(edit.isListOpened())
                                self.key(ckit.VK_SPACE, ckit.MODKEY_ALT, system=True)
                                self.assertTrue(edit.getAutoComplete())
                                self.key(ckit.VK_TAB)
                                self.assertEqual(bool(edit.isListOpened()), mode != "off")
                                before = (edit.getText(), edit.getSelection())
                                self.key(ckit.VK_SPACE, ckit.MODKEY_ALT, system=True)
                                self.assertFalse(edit.getAutoComplete())
                                self.assertFalse(edit.isListOpened())
                                self.assertEqual((edit.getText(), edit.getSelection()), before)
                                self.assertEqual(self.window.commandline_history, ["runtime-history"])
                                self.assertEqual(clnch_ini.get("MISC", "auto_complete"), str(initial))
                                edit.setText("")
                                edit.setSelection([0, 0])
                                for ch in raw:
                                    user32.SendMessageW(self.window.getHWND(), 0x0102, ord(ch), 1)
                                self.assertEqual(edit.getText(), raw)
                                self.assertFalse(edit.isListOpened())
                                self.key(ckit.VK_RETURN)
                            self.input_action("runtime-", switch)
                            self.assertEqual(executed[-1], '  "a  b"  ')
                            self.assertEqual(self.window.commandline_history, [raw, "runtime-history"])
                self.assertEqual(len(executed), 6)

            def test_native_ini_read_failure_protects_settings_and_recovers(self):
                import clnch_strings_en
                import clnch_strings_ja

                path = Path(clnch_ini.ini_filename)
                valid = b"[OTHER]\r\nkeep = original\r\n[COMMANDLINE]\r\nhistory_0 = saved\r\n"
                for broken in (b"[broken\r\n" + valid,
                               b"[OTHER]\r\nkeep = original\r\n[OTHER]\r\n" + valid,
                               valid + b"invalid line\r\n"):
                    with self.subTest(broken=broken):
                        path.write_bytes(broken)
                        clnch_ini.read()
                        window = clnch_mainwindow.MainWindow()
                        window.console_window.unregisterStdio()
                        try:
                            window.configure()
                            self.assertEqual(window.input_settings["HISTORY_MODE"], "persistent")
                            self.assertEqual(window.commandline_history, [])
                            console = window.console_window
                            for definitions in (clnch_strings_en, clnch_strings_ja):
                                console.clearLog()
                                console.registerStdio()
                                try:
                                    with patch.object(strings, "INI_READ_ERROR", definitions.INI_READ_ERROR):
                                        window.start()
                                finally:
                                    console.unregisterStdio()
                                self.assertIn(definitions.INI_READ_ERROR.format(path=path), "\n".join(console.log.log))
                                self.assertTrue(console.auto_show_required)
                                console.onTimerAutoShow()
                                self.assertTrue(console.opened)
                                console.show(False)
                            window.commandline_history = ["new history"]
                            window._onActivate(False)
                            window._onEndSession()
                            clnch_configmenu._saveModifierSettings(window, ctrl_action="execute")
                            window.saveState()
                            clnch_ini.write()
                            self.assertTrue(clnch_ini.dirty)
                            self.assertEqual(path.read_bytes(), broken)
                            self.assertEqual(list(data.glob("reclnch.ini.*.tmp")), [])
                            path.write_bytes(valid)
                            clnch_ini.write()
                            self.assertEqual(path.read_bytes(), valid)
                            window.stop()
                        finally:
                            window.destroy()
                        # A fresh startup rereads the repaired file; Reload does not read INI.
                        clnch_ini.read()
                        window = clnch_mainwindow.MainWindow()
                        window.console_window.unregisterStdio()
                        try:
                            window.configure()
                            self.assertFalse(clnch_ini.read_failed)
                            self.assertEqual(window.commandline_history, ["saved"])
                            output = io.StringIO()
                            with contextlib.redirect_stdout(output):
                                window.start()
                            self.assertNotIn(strings.INI_READ_ERROR.format(path=path), output.getvalue())
                            window.commandline_history.insert(0, "after repair")
                            window._onActivate(False)
                            self.assertFalse(clnch_ini.dirty)
                            disk = configparser.RawConfigParser()
                            disk.read(path, encoding="utf-8")
                            self.assertEqual(disk.get("OTHER", "keep"), "original")
                            self.assertEqual(disk.get("COMMANDLINE", "history_0"), "after repair")
                            self.assertEqual(disk.get("COMMANDLINE", "history_1"), "saved")
                            window.stop()
                        finally:
                            window.destroy()

            def test_native_first_ini_startup_saves_settings_and_history(self):
                path = Path(clnch_ini.ini_filename)
                path.unlink(missing_ok=True)
                clnch_ini.read()
                window = clnch_mainwindow.MainWindow()
                window.console_window.unregisterStdio()
                try:
                    window.configure()
                    self.assertFalse(clnch_ini.read_failed)
                    window.commandline_history = ["first history"]
                    window._onActivate(False)
                    self.assertFalse(clnch_ini.dirty)
                    clnch_ini.read()
                    self.assertEqual(clnch_ini.get("COMMANDLINE", "history_0"), "first history")
                    self.assertEqual(clnch_ini.getint("GEOMETRY", "width"), window.width())
                finally:
                    window.destroy()

            def test_native_nonpersistent_startup_removes_saved_history(self):
                for mode in ("off", "session"):
                    with self.subTest(mode=mode):
                        clnch_ini.set("INPUT", "history_mode", mode)
                        for key in ("history_0", "history_7", "history_1007"):
                            clnch_ini.set("COMMANDLINE", key, "old history")
                        clnch_ini.set("COMMANDLINE", "keep", "other setting")
                        clnch_ini.write()
                        clnch_ini.read()
                        window = clnch_mainwindow.MainWindow()
                        window.console_window.unregisterStdio()
                        try:
                            self.assertEqual(window.input_settings["HISTORY_MODE"], "off")
                            window.configure()
                            self.assertEqual(window.input_settings["HISTORY_MODE"], mode)
                            self.assertEqual(window.commandline_history, [])
                            disk = configparser.RawConfigParser()
                            disk.read(clnch_ini.ini_filename, encoding="utf-8")
                            self.assertEqual(dict(disk.items("COMMANDLINE")), {"keep": "other setting"})
                        finally:
                            window.destroy()

            def test_native_history_mode_menu_deletes_saved_history(self):
                import clnch_listwindow
                clnch_ini.set("COMMANDLINE", "history_0", "saved")
                self.window.applyInputSettings(dict(self.window.input_settings, HISTORY_MODE="persistent"))
                original = clnch_listwindow.ListWindow
                errors = []
                selected = [0]
                def create(*args, **kwargs):
                    listing = original(*args, **kwargs)
                    def drive():
                        listing.killTimer(drive)
                        try:
                            self.assertEqual(args[8], strings.INPUT_HISTORY)
                            self.assertEqual([item[0] for item in args[9]], [
                                strings.INPUT_HISTORY_OFF + strings.HISTORY_RESET_NOTICE,
                                strings.INPUT_HISTORY_SESSION + strings.HISTORY_RESET_NOTICE,
                                strings.INPUT_HISTORY_PERSISTENT])
                            if selected[0] < 0:
                                self.key(ckit.VK_ESCAPE, window=listing)
                            else:
                                self.key(ckit.VK_HOME, window=listing)
                                for _ in range(selected[0]):
                                    self.key(ckit.VK_DOWN, window=listing)
                                self.key(ckit.VK_RETURN, window=listing)
                        except BaseException as error:  # noqa: BLE001  # Surface native timer assertions after closing the menu.
                            errors.append(error)
                            listing.cancel()
                    listing.setTimer(drive, 30)
                    return listing
                for choice in (-1, 0, 2, 1, 2):
                    selected[0] = choice
                    before = self.window.commandline_history[:]
                    with patch.object(clnch_listwindow, "ListWindow", side_effect=create):
                        clnch_configmenu._configInputSetting(self.window, "HISTORY_MODE")
                    self.assertEqual(errors, [])
                    if choice < 0:
                        self.assertEqual(self.window.commandline_history, before)
                        continue
                    self.assertEqual(self.window.commandline_history, [])
                    disk = configparser.RawConfigParser()
                    disk.read(clnch_ini.ini_filename, encoding="utf-8")
                    self.assertEqual(disk.get("INPUT", "history_mode"),
                        ("off", "session", "persistent")[choice])
                    self.assertFalse(disk.has_option("COMMANDLINE", "history_0"))
                    if choice == 2:
                        self.window.commandline_history = ["memory history"]
                    elif choice == 1:
                        self.input_action("about", lambda: self.key(ckit.VK_RETURN))
                        self.assertEqual(self.window.commandline_history, ["about"])
                        self.window.configure()
                        self.assertEqual(self.window.commandline_history, ["about"])

            def test_native_empty_history_input_modes_and_ini_roundtrip(self):
                calls = []
                self.window.launcher.command_list.extend(
                    (name, lambda info: calls.append(info.arg_string)) for name in ("", "probe"))
                for mode in ("off", "session", "persistent"):
                    with self.subTest(mode=mode):
                        self.window.applyInputSettings(dict(self.window.input_settings, HISTORY_MODE="off"))
                        for i, entry in enumerate(("", "saved", "", "previous", "")):
                            clnch_ini.set("COMMANDLINE", f"history_{i}", entry)
                        clnch_ini.write()
                        clnch_ini.read()
                        saved = clnch_ini.ini.items("COMMANDLINE")
                        self.window.applyInputSettings(dict(self.window.input_settings, HISTORY_MODE=mode))
                        expected = ["saved", "previous"] if mode == "persistent" else []
                        self.assertEqual(self.window.commandline_history, expected)
                        self.assertEqual(clnch_ini.ini.items("COMMANDLINE"),
                            saved if mode == "persistent" else [])
                        before = len(calls)
                        self.input_action("", lambda: self.key(ckit.VK_RETURN))
                        self.assertEqual(len(calls), before + 1)
                        self.assertEqual(self.window.commandline_history, expected)
                        # An ordinary command key uses the same history boundary.
                        self.window.cmd_keymap["F2"] = lambda info: calls.append(info.arg_string)
                        self.input_action("", lambda: self.key(ckit.VK_F2))
                        self.assertEqual(len(calls), before + 2)
                        self.assertEqual(self.window.commandline_history, expected)
                        self.input_action("probe;日本語  args", lambda: self.key(ckit.VK_RETURN))
                        if mode != "off":
                            expected = ["probe;日本語  args", *expected]
                        self.assertEqual(self.window.commandline_history, expected)
                        self.window.commandLineHistorySave()
                        self.assertEqual(clnch_ini.ini.items("COMMANDLINE"),
                            [(f"history_{i}", entry) for i, entry in enumerate(expected)]
                            if mode == "persistent" else [])
                        clnch_ini.write()
                        clnch_ini.read()
                        self.assertEqual(self.window.commandLineHistoryLoad(),
                            expected if mode == "persistent" else [])
                        self.input_action("  ", lambda: self.key(ckit.VK_F2))
                        self.assertEqual(self.window.commandline_history,
                            ["  ", *expected] if mode != "off" else expected)

            def test_native_lowercase_builtins_and_case_insensitive_history(self):
                clnch_ini.set("MISC", "auto_complete", "1")
                names = [name for name, _handler in self.window.launcher.command_list]
                self.assertEqual(names, ["history", "config", "reload", "about", "quit", "_ra", "new", "customonly"])
                self.window.input_settings["HISTORY_MODE"] = "session"
                self.window.commandline_history = []
                for text in ("about", "ABOUT", "About"):
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        self.input_action(text, lambda: self.key(ckit.VK_RETURN))
                    self.assertIn("ReCraftLaunch", output.getvalue())
                    self.assertEqual(self.window.commandline_history, [text])
                def check_candidates():
                    edit = self.window.commandline_edit
                    self.assertEqual(edit.candidate_handler(ckit.EditWidget.UpdateInfo("AB", [2, 2])), (["about"], 0))
                    self.key(ckit.VK_TAB)
                    self.assertEqual(edit.getText(), "about")
                    self.key(ord("K"), 2)
                    self.assertEqual(self.window.commandline_history, [])
                self.input_action("AB", check_candidates)

            def probe_action(self, output, **fields):
                return {"link": str(pythonw), "args": subprocess.list2cmdline(
                    ["-B", "-S", str(probe), str(output)]), **fields}

            def result(self, output):
                self.pump(output.exists)
                self.pump(lambda: ckit.JobQueue.defaultQueue().numItems() == 0)
                result = json.loads(output.read_text(encoding="utf-8"))
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
                kernel32.OpenProcess.restype = wintypes.HANDLE
                kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
                kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
                process = kernel32.OpenProcess(0x100000, False, result["pid"])
                if process:
                    try:
                        self.assertEqual(kernel32.WaitForSingleObject(process, 5000), 0)
                    finally:
                        kernel32.CloseHandle(process)
                return result

            def test_native_edit_is_json_only_and_launches_external_editor(self):
                self.assertFalse(hasattr(self.window, "editor"))
                self.assertFalse(hasattr(self.window, "command_Edit"))
                self.assertNotIn("Edit", list(self.window.enumCommand()))
                self.assertFalse(self.window.executeCommand("Edit", ckit.CommandInfo()))
                self.assertNotIn("edit", dict(self.window.launcher.command_list))
                self.assertFalse(self.window.launcher.onEnter(None, "edit;file.txt", 0))
                output = data / "registered-editor.json"
                document = data / "既存 file.txt"
                document.write_text("keep contents", encoding="utf-8")
                target = self.probe_action(output, workdir=str(data))
                target["args"] += " " + subprocess.list2cmdline([str(document)])
                self.apply({"edit": {"target": target}, "alias": {"target": {"link": "edit"}}})
                for name in ("EdIt", "alias"):
                    with self.subTest(name=name):
                        output.unlink(missing_ok=True)
                        self.input_action(name + ';"未作成 file.txt" C:\\tail', lambda: self.key(ckit.VK_RETURN))
                        result = self.result(output)
                        self.assertEqual(result["args"], [str(document), "未作成 file.txt", "C:\\tail"])
                        self.assertEqual(result["cwd"], str(data))
                self.assertEqual(document.read_text(encoding="utf-8"), "keep contents")
                self.window.configure()
                self.assertIn("edit", dict(self.window.launcher.command_list))
                self.ui = self.window.cmd_keymap["F12"].__self__
                self.apply({})
                self.window.configure()
                self.assertNotIn("edit", dict(self.window.launcher.command_list))
                self.assertFalse(hasattr(self.window, "editor"))
                self.assertFalse(self.window.launcher.onEnter(None, "EDIT", 0))

            def test_shell_arguments_workdir_alias_and_view_modes(self):
                child, parent = data / "child", data / "parent"
                child.mkdir(exist_ok=True)
                parent.mkdir(exist_ok=True)
                for mode, state in (("normal", (False, False)),
                                    ("minimized", (True, False)),
                                    ("maximized", (False, True))):
                    with self.subTest(mode=mode):
                        output = data / (mode + ".json")
                        self.apply({"alias": {"target": {"link": "probe",
                            "args": '"固定 文書.txt" --fixed', "workdir": str(parent), "view_mode": mode}},
                            "probe": {"target": self.probe_action(output, workdir=str(child), view_mode="minimized")}})
                        self.invoke("alias", ["動的 文書.txt", "C:\\tail\\"])
                        result = self.result(output)
                        self.assertEqual(result["args"], ["固定 文書.txt", "--fixed", "動的 文書.txt", "C:\\tail\\"])
                        self.assertEqual(result["cwd"], str(parent))
                        self.assertEqual((result["minimized"], result["maximized"]), state)

            def test_shell_placeholder_and_child_context_defaults(self):
                for placeholder in (False, True):
                    with self.subTest(placeholder=placeholder):
                        output = data / ("placeholder" + str(placeholder) + ".json")
                        target = self.probe_action(output, workdir=str(data), view_mode="minimized")
                        target["args"] += " --before %param% --after" if placeholder else " --before"
                        self.apply({"alias": {"target": {"link": "probe"}}, "probe": {"target": target}})
                        self.invoke("alias", ["a b", "日本語"])
                        result = self.result(output)
                        expected = ["--before", "a b", "日本語"] + (["--after"] if placeholder else [])
                        self.assertEqual(result["args"], expected)
                        self.assertEqual(result["cwd"], str(data))
                        self.assertFalse(result["minimized"])
                        self.assertFalse(result["maximized"])

            def test_dynamic_arguments_reach_child_unchanged(self):
                cases = [['a"b', "C:\\tail\\"],
                         ["", "a\tb", "C:\\two words\\", 'a' + "\\" * 3 + '"b', "日本語😀", " leading "]]
                for index, args in enumerate(cases):
                    with self.subTest(args=args):
                        output = data / ("dynamic-quotes" + str(index) + ".json")
                        self.apply({"probe": {"target": self.probe_action(output)}})
                        self.invoke("probe", args)
                        self.assertEqual(self.result(output)["args"], args)

            def test_native_raw_argument_strings_reach_shell_and_child(self):
                from clnch_commandplatform import split_commandline_args
                from test_argument_strings import CASES

                real_shell = clnch_mainwindow.pyauto.shellExecute
                # Exercise runas delegation without displaying/approving a UAC prompt.
                def launch(verb, *args):
                    return real_shell(None if verb == "runas" else verb, *args)
                for index, (raw, expected_argv) in enumerate(CASES):
                    for route in ("registered", "fixed", "alias", "system", "file", "quoted-file",
                                  "association", "quoted-association", "ra", "ipc"):
                        if route == "fixed" and "%" in raw:
                            continue  # Fixed Args retains macro expansion; runtime input is literal.
                        with self.subTest(raw=raw, route=route):
                            output = data / ("raw-" + str(index) + "-" + route + ".json")
                            action = self.probe_action(output)
                            prefix = action["args"]
                            params = prefix + (" " + raw if raw else "")
                            argv = expected_argv
                            self.window.association_list = []
                            if route == "fixed":
                                action["args"] = params
                            self.apply({"probe": {"target": action},
                                        "middle": {"target": {"link": "probe", "args": "%param%"}},
                                        "alias": {"target": {"link": "middle", "args": "%param%"}}})
                            if route in ("registered", "alias", "ipc"):
                                text = ("alias" if route == "alias" else "probe") + ";" + raw
                            elif route == "fixed":
                                text = "probe"
                            elif route == "ra":
                                text = "_ra;probe " + raw
                            elif route in ("association", "quoted-association"):
                                document = data / "関連付け file.txt"
                                document.touch()
                                self.window.association_list = [("*.txt", self.window.ShellExecuteCommand(
                                    None, str(pythonw), prefix + " %param%", ""))]
                                text = ('"' + str(document) + '"' if route == "quoted-association"
                                        else str(document)) + ";" + raw
                                params = prefix + " " + subprocess.list2cmdline([str(document)]) + " " + raw
                                argv = [str(document), *expected_argv]
                            else:
                                target = "pythonw" if route == "system" else str(pythonw)
                                if route == "quoted-file":
                                    target = '"' + target + '"'
                                text = target + ";" + params
                            with (patch.dict(os.environ, PATH=str(pythonw.parent)),
                                  patch.object(clnch_mainwindow.pyauto, "shellExecute", side_effect=launch) as opened):
                                if route == "ipc":
                                    ipc = clnch_ipc.IpcData()
                                    ipc.trySetOption("--execute", text)
                                    clnch_ipc.IpcData(ipc.getValue()).execute(self.window)
                                else:
                                    self.input_action(text, lambda: self.key(ckit.VK_RETURN))
                                result = self.result(output)
                                opened.assert_called_once()
                                self.assertEqual(opened.call_args.args[2], params)
                                self.assertEqual(opened.call_args.args[0], "runas" if route == "ra" else None)
                            self.assertEqual(result["args"], argv)
                            self.assertTrue(result["command_line"].endswith(params), result["command_line"])
                            self.assertEqual(split_commandline_args(params)[4:], argv)

            def test_native_ra_document_static_association_reaches_child(self):
                import clnch_commandplatform

                document = data / "関連付け document.txt"
                document.touch()
                raw = '  "日本語 arg" "" one;two  '
                real_shell = clnch_mainwindow.pyauto.shellExecute
                for route in ("direct", "json", "alias"):
                    output = data / ("ra-document-" + route + ".json")
                    action = self.probe_action(output)
                    values = {1: '"' + action["link"] + '" ' + action["args"] + ' --fixed "%1" %*',
                              2: action["link"]}
                    self.apply({"doc": {"target": {"link": str(document)}},
                                "alias": {"target": {"link": "doc", "args": "--alias"}},
                                "json": {"target": {"link": "_ra", "args": '"' + str(document) + '"',
                                                    "workdir": str(data), "view_mode": "minimized"}}})
                    text = ('_ra;"' + str(document) + '" ' if route == "direct" else
                            "json;" if route == "json" else "_ra;alias ") + raw
                    # Preserve the real JobQueue and Shell call; only UAC is replaced with non-elevated launch.
                    def launch(verb, *args):
                        self.assertEqual(verb, "runas")
                        return real_shell(None, *args)
                    with patch.object(clnch_commandplatform, "_association_string",
                                      side_effect=lambda extension, kind, values=values: values.get(kind)), \
                            patch.object(clnch_mainwindow.pyauto, "shellExecute", side_effect=launch) as opened:
                        self.input_action(text, lambda: self.key(ckit.VK_RETURN))
                        result = self.result(output)
                        opened.assert_called_once()
                        self.assertEqual(opened.call_args.args[1], action["link"])
                        self.assertTrue(opened.call_args.args[2].endswith(raw))
                    self.assertEqual(result["args"], ["--fixed", str(document),
                                                     *(["--alias"] if route == "alias" else []),
                                                     "日本語 arg", "", "one;two"])
                    self.assertEqual(result["cwd"], str(data))
                    self.assertEqual((result["minimized"], result["maximized"]), (route == "json", False))

            def test_native_quoted_file_and_folder_input_history(self):
                self.window.input_settings.update(HISTORY_MODE="session")
                folder = data / "引用符  folder"
                folder.mkdir()
                document = folder / "日本語 file.txt"
                document.touch()
                self.window.association_list = []
                for path in (str(document), str(folder), str(folder) + "\\"):
                    for suffix in ("", ';  "a b" "" one;two C:\\tail\\  '):
                        text = '"' + path + '"' + suffix
                        with self.subTest(text=text), patch.object(clnch_mainwindow.pyauto, "shellExecute") as opened:
                            self.input_action(text, lambda: self.key(ckit.VK_RETURN))
                            self.pump(lambda: opened.called)
                            opened.assert_called_once_with(None, path, suffix[1:], ckit.splitPath(path)[0])
                            self.assertEqual(self.window.commandline_history[0], text)
                            self.assertIsNone(self.window.commandline_edit)

            def test_native_context_menu_paths_and_missing_input_preservation(self):
                folder = data / "menu 日本語 folder"
                folder.mkdir()
                document = folder / "a file.txt"
                document.touch()
                for layout, key in (("101", "C-Slash"), ("106", "C-BackSlash")):
                    clnch_ini.set("MISC", "default_keymap", layout)
                    self.window.configure()
                    self.window.input_settings.update(HISTORY_MODE="session")
                    binding = self.window.cmd_keymap[key]
                    event = next(event for event, func in self.window.cmd_keymap.table.items() if func is binding)
                    for text in ("", "unknown-menu-target", str(document) + ".missing",
                                 '"' + str(document), str(document) + '"', '""' + str(document) + '""',
                                 '"' + str(document) + '.missing"', "unknown;raw;tail"):
                        def unchanged(text=text, event=event):
                            edit = self.window.commandline_edit
                            edit.setSelection([0, len(text)])
                            session = self.window.keydown_hook.__self__
                            history = self.window.commandline_history[:]
                            with patch.object(self.window, "quit", wraps=self.window.quit) as quit_input:
                                self.key(event.vk, event.mod)
                                quit_input.assert_not_called()
                            self.assertIs(self.window.commandline_edit, edit)
                            self.assertIs(self.window.keydown_hook.__self__, session)
                            self.assertEqual(edit.getText(), text)
                            self.assertEqual(edit.getSelection(), [0, len(text)])
                            self.assertEqual(self.window.commandline_history, history)
                        with self.subTest(layout=layout, text=text), patch.object(
                                clnch_mainwindow.clnch_native, "popupContextMenu") as popup:
                            self.input_action(text, unchanged)
                            popup.assert_not_called()
                    for path in (str(document), str(folder), str(folder) + "\\"):
                        for quoted in (False, True):
                            text = ('"' + path + '"' if quoted else path) + ';  "a b" one;two'
                            with self.subTest(layout=layout, text=text), patch.object(
                                    clnch_mainwindow.clnch_native, "popupContextMenu") as popup:
                                self.input_action(text, lambda event=event: self.key(event.vk, event.mod))
                                dirname, name = os.path.split(os.path.normpath(path))
                                self.assertEqual(popup.call_count, 1)
                                self.assertEqual(popup.call_args.args[3:], (dirname, [name]))
                                self.assertEqual(self.window.commandline_history[0], text)

            def test_native_missing_drive_and_registered_name_whitespace(self):
                self.window.input_settings.update(HISTORY_MODE="session")
                missing = next(chr(letter) + ":" for letter in range(ord("Z"), ord("D"), -1)
                               if not os.path.exists(chr(letter) + ":\\"))
                with patch.object(clnch_mainwindow.pyauto, "shellExecute") as shell:
                    for text in (missing, missing + "\\", missing + "\\something"):
                        def unchanged(text=text):
                            edit = self.window.commandline_edit
                            session = self.window.keydown_hook.__self__
                            edit.setSelection([0, len(text)])
                            history = self.window.commandline_history[:]
                            with patch.object(self.window, "quit", wraps=self.window.quit) as quit_input:
                                self.key(ckit.VK_RETURN)
                                quit_input.assert_not_called()
                            self.assertIs(self.window.commandline_edit, edit)
                            self.assertIs(self.window.keydown_hook.__self__, session)
                            self.assertEqual((edit.getText(), edit.getSelection()), (text, [0, len(text)]))
                            self.assertEqual(self.window.commandline_history, history)
                        self.input_action(text, unchanged)
                    shell.assert_not_called()
                    root = Path(data).anchor
                    self.input_action(root[:2], lambda: self.key(ckit.VK_RETURN))
                    self.pump(lambda: shell.called)
                    self.assertEqual(shell.call_args.args[:2], (None, root.upper()))
                    self.assertEqual(self.window.commandline_history[0], root[:2])
                output = data / "whitespace-priority.json"
                self.apply({"notepad": {"target": self.probe_action(output)},
                            "alias": {"target": {"link": "notepad"}}})
                raw = '  "a b" "" one;two C:\\tail\\  '
                for name in ("notepad ", " NoTePaD ", "\u3000notepad\u3000", " alias "):
                    output.unlink(missing_ok=True)
                    text = name + ";" + raw
                    with patch.object(clnch_commandplatform, "resolve_system_executable", side_effect=AssertionError("registration must win")):
                        self.input_action(text, lambda: self.key(ckit.VK_RETURN))
                        result = self.result(output)
                    self.assertEqual(result["args"], ["a b", "", "one;two", "C:\\tail\\"])
                    self.assertTrue(result["command_line"].endswith(raw))
                    self.assertEqual(self.window.commandline_history[0], text)

            def test_native_spaces_keys_paste_history_and_settings(self):
                clnch_ini.set("MISC", "auto_complete", "1")
                self.window.applyInputSettings(dict(self.window.input_settings,
                    HISTORY_MODE="session", COMPLETION_MODE="standard"))
                for index, mode in ((1, "complete"), (0, "insert"), (1, "complete")):
                    with patch.object(clnch_configmenu.clnch_listwindow, "popMenu", return_value=index):
                        clnch_configmenu._configInputSetting(self.window, "SPACE_ACTION")
                    self.assertEqual(self.window.input_settings["SPACE_ACTION"], mode)
                    self.assertEqual(clnch_ini.get("INPUT", "space_action"), mode)
                    if mode == "insert":
                        self.assertIs(self.window.keymap["Space"], self.window._input_key_commands["SPACE_ACTION"])
                    else:
                        self.assertNotIn(ckit.KeyEvent(ckit.VK_SPACE, 0), self.window.keymap.table)
                    self.assertNotIn(ckit.KeyEvent(ckit.VK_TAB, 0), self.window.cmd_keymap.table)
                    self.assertEqual(self.window.input_settings["TAB_ACTION"], "complete")
                    self.assertEqual(self.window.input_settings["COMPLETION_MODE"], "standard")
                    def exercise(mode=mode):
                        edit = self.window.commandline_edit
                        if mode == "insert":
                            self.window.command.AutoCompleteOff()
                            edit.setText("cmd")
                            edit.setSelection([3, 3])
                            self.key(ckit.VK_SPACE)
                            self.key(ckit.VK_SPACE)
                            user32.SendMessageW(self.window.getHWND(), 0x0102, ord("a"), 1)
                            self.assertEqual(edit.getText(), "cmd  a")
                        else:
                            self.window.commandline_history[:] = ["spaceprobe  alpha", "spaceprobe  beta"]
                            edit.setText("spaceprob")
                            edit.setSelection([9, 9])
                            user32.SendMessageW(self.window.getHWND(), 0x0102, ord("e"), 1)
                            self.assertEqual(edit.getText(), "spaceprobe  alpha")
                            self.key(ckit.VK_SPACE)
                            self.assertEqual(edit.getText(), "spaceprobe  beta")
                            self.key(ckit.VK_SPACE)
                            self.assertEqual(edit.getText(), "spaceprobe  alpha")
                            self.key(ckit.VK_SPACE, ckit.MODKEY_SHIFT)
                            self.assertEqual(edit.getText(), "spaceprobe  beta")
                        line = self.window.keydown_hook.__self__
                        for text in ("cmd  arg", "cmd;one  two", r"C:\My  Tools\app.exe",
                                     "https://example.invalid/a  b;q=one  two", "  cmd  arg  "):
                            edit.setText("replace")
                            edit.setSelection([0, 7])
                            ckit.setClipboardText(text)
                            self.key(ord("V"), ckit.MODKEY_CTRL)
                            self.assertEqual(edit.getText(), text)
                            line.appendHistory(text)
                            self.assertEqual(self.window.commandline_history[0], text)
                        self.window.command.AutoCompleteOn()
                        self.window.commandline_history[:] = ["cmd  arg"]
                        edit.setText("cmd")
                        edit.setSelection([3, 3])
                        self.key(ckit.VK_TAB)
                        self.assertEqual(edit.getText(), "cmd  arg")
                    self.input_action("", exercise)
                self.window.commandLineHistorySave()
                self.assertNotIn("preserve_multiple_spaces", Path(clnch_ini.ini_filename).read_text(encoding="utf-8"))

            def test_native_windows_argument_completion_and_semicolon_input(self):
                clnch_ini.set("MISC", "auto_complete", "1")
                self.window.input_settings.update(COMPLETION_MODE="standard",
                                                  HISTORY_MODE="session")
                self.window.commandline_history = ["probe;one;two"]
                def complete():
                    edit = self.window.commandline_edit
                    edit.setText("probe;one;t")
                    self.key(ckit.VK_TAB)
                    self.assertEqual(edit.getText(), "probe;one;two")
                    edit.setSelection([len("probe;one;t"), len("probe;one;two")])
                    user32.SendMessageW(self.window.getHWND(), 0x0102, ord(";"), 1)
                    self.assertEqual(edit.getText(), "probe;one;t;")
                    raw = 'probe;  "a  b" "" one;two  '
                    edit.setText(raw)
                    self.assertEqual(edit.getText(), raw)
                    self.key(ckit.VK_RETURN)
                calls = []
                self.window.launcher.command_list.append(("probe", lambda info: calls.append(info)))
                self.input_action("probe;one;t", complete)
                self.assertEqual(calls[0].arg_string, '  "a  b" "" one;two  ')
                self.assertEqual(self.window.commandline_history[0], 'probe;  "a  b" "" one;two  ')

            def test_shell_path_placeholders_are_unquoted(self):
                workdir = data / "作業 folder"
                workdir.mkdir()
                output = data / "path-placeholders.json"
                fixed = self.probe_action(output)["args"]
                # A custom ShellExecuteCommand keeps fixed params separate from runtime args.
                command = self.window.ShellExecuteCommand(
                    None, str(pythonw), fixed, "%param%")
                command(SimpleNamespace(args=[str(workdir) + "\\"]))
                result = self.result(output)
                self.assertEqual(result["args"], [])
                self.assertEqual(result["cwd"], str(workdir))
                output = data / "filename-placeholder.json"
                executable = workdir / "起動 probe.exe"
                shutil.copy2(pythonw, executable)
                shutil.copy2(pythonw.parent / "python315.dll", workdir / "python315.dll")
                command = self.window.ShellExecuteCommand(
                    None, "%param%", self.probe_action(output)["args"], str(workdir))
                with patch.dict(os.environ, PYTHONHOME=str(pythonw.parent)):
                    command(SimpleNamespace(args=[str(executable)]))
                    result = self.result(output)
                self.assertEqual(result["args"], [])
                self.assertEqual(result["cwd"], str(workdir))

            def test_f12_native_clipboard_and_cycle(self):
                self.apply({"alias": {"target": {"link": "child"}},
                            "child": {"target": {"link": str(probe)}},
                            "cycle": {"target": {"link": "cycle"}}})
                self.window.commandline_edit = ckit.EditWidget(self.window, 0, 0, 20, 1, "ALIAS;arg")
                self.addCleanup(self.window.commandline_edit.destroy)
                ckit.setClipboardText("sentinel")
                self.window.cmd_keymap["F12"](None)
                self.assertEqual(ckit.getClipboardText(), str(probe))
                self.window.commandline_edit.setText("cycle")
                self.window.cmd_keymap["F12"](None)
                self.assertEqual(ckit.getClipboardText(), str(probe))
                for link in ("notepad.exe", "%RECRAFT_FOLDER%/notepad.exe", "missing/notepad.exe"):
                    self.apply({"alias": {"target": {"link": "middle"}},
                                "middle": {"target": {"link": "child"}},
                                "child": {"target": {"link": link}}})
                    self.window.commandline_edit.setText("alias;ignored")
                    self.window.cmd_keymap["F12"](None)
                    self.assertEqual(ckit.getClipboardText(), link)
                self.window.commandline_edit = None

            def test_shell_absolute_and_environment_targets(self):
                # Compare path interpretation with the actual ShellExecuteCommand/child.
                for index, link in enumerate((str(pythonw), "%RECRAFT_TARGET%", "%param%",
                                              '"' + str(pythonw) + '"', '"%RECRAFT_TARGET%"', '"%param%"')):
                    with self.subTest(link=link), patch.dict(os.environ, RECRAFT_TARGET=str(pythonw)):
                        output = data / f"target-resolution-{index}.json"
                        self.apply({"probe": {"target": self.probe_action(output, link=link)}})
                        args = [str(pythonw)] if "%param%" in link else []
                        self.invoke("probe", args)
                        result = self.result(output)
                        self.assertEqual(result["cwd"], str(pythonw.parent))
                        self.assertEqual(result["args"], args)

            def test_native_quoted_link_alias_child_workdir(self):
                folder = data / "quoted 日本語 target"
                folder.mkdir()
                executable = folder / "起動 file.exe"
                shutil.copy2(pythonw, executable)
                shutil.copy2(pythonw.parent / "python315.dll", folder / "python315.dll")
                raw = '  "a b" "" one;two C:\\tail\\  '
                with patch.dict(os.environ, PYTHONHOME=str(pythonw.parent), RECRAFT_TARGET=str(executable)):
                    for index, link in enumerate(('"' + str(executable) + '"', '"%RECRAFT_TARGET%"')):
                        for workdir in ("", str(data)):
                            output = data / f"quoted-link-{index}-{bool(workdir)}.json"
                            self.apply({"outer": {"target": {"link": "middle", "workdir": workdir}},
                                "middle": {"target": {"link": "child"}},
                                "child": {"target": self.probe_action(output, link=link)}})
                            text = "outer;" + raw
                            self.input_action(text, lambda: self.key(ckit.VK_RETURN))
                            result = self.result(output)
                            self.assertEqual(result["cwd"], workdir or str(folder))
                            self.assertEqual(result["args"], ["a b", "", "one;two", "C:\\tail\\"])
                            self.assertTrue(result["command_line"].endswith(raw))
                    ckit.setClipboardText("sentinel")
                    self.input_action("outer", lambda: self.key(ckit.VK_F12))
                    self.assertEqual(ckit.getClipboardText(), '"%RECRAFT_TARGET%"')

            def test_native_target_and_mapped_folders_use_real_os_search(self):
                import clnch_commandexecutor

                self.window.modifier_settings.update(CTRL_ACTION="mapped_folder",
                    SOURCE_ROOTS=(str(pythonw.parent),), CTRL_DESTINATION_ROOT=str(data))
                with patch.dict(os.environ, PATH=str(pythonw.parent), PATHEXT=".EXE",
                                RECRAFT_FOLDER=str(pythonw.parent)):
                    for link, workdir in ((str(pythonw), ""),
                                          ('"' + str(pythonw) + '"', ""),
                                          ('"%RECRAFT_FOLDER%/pythonw.exe"', ""),
                                          ('"' + str(pythonw.parent) + '\\"', ""),
                                          (pythonw.stem, ""), (pythonw.name, ""),
                                          ("%RECRAFT_FOLDER%/pythonw.exe", ""),
                                          (str(pythonw.parent), "")):
                        with self.subTest(link=link):
                            self.apply({"outer": {"target": {"link": "middle", "workdir": workdir}},
                                "middle": {"target": {"link": "child"}}, "child": {"target": {"link": link}}})
                            with patch.object(clnch_commandexecutor, "shellExecute") as opened:
                                self.invoke("outer", mod=ckit.MODKEY_SHIFT)
                                self.pump(lambda: ckit.JobQueue.defaultQueue().numItems() == 0)
                                opened.assert_called_once_with(None, str(pythonw.parent), "", "")
                                opened.reset_mock()
                                self.invoke("outer", mod=ckit.MODKEY_CTRL)
                                self.pump(lambda: ckit.JobQueue.defaultQueue().numItems() == 0)
                                opened.assert_called_once_with(None, str(data), "", "")
                    for link in (str(data / "missing.exe"), "missing-" + uuid.uuid4().hex + ".exe"):
                        self.apply({"missing": {"target": {"link": link}}})
                        self.window.modifier_settings["SOURCE_ROOTS"] = (str(ROOT), str(data))
                        with patch.object(clnch_commandexecutor, "shellExecute") as opened:
                            for mod in (ckit.MODKEY_CTRL, ckit.MODKEY_SHIFT):
                                self.invoke("missing", mod=mod)
                            self.pump(lambda: ckit.JobQueue.defaultQueue().numItems() == 0)
                            opened.assert_not_called()
                notepad = clnch_commandplatform.resolve_system_executable("notepad.exe")
                self.assertIsNotNone(notepad)
                self.assertEqual(clnch_commandplatform._get_target_dir("notepad.exe"),
                                 str(Path(notepad).resolve().parent))

            def test_native_folder_jobs_keep_input_responsive_and_queue_order(self):
                import clnch_commandexecutor

                self.apply({"outer": {"target": {"link": "child", "args": '"fixed arg"'}},
                            "child": {"target": {"link": "tool.exe"}}})
                self.window.modifier_settings.update(CTRL_ACTION="mapped_folder",
                    SOURCE_ROOTS=(str(data),), CTRL_DESTINATION_ROOT=str(data))
                self.window.input_settings["HISTORY_MODE"] = "session"
                owner = threading.get_ident()
                for mod in (ckit.MODKEY_SHIFT, ckit.MODKEY_CTRL):
                    helper = "_get_target_dir" if mod == ckit.MODKEY_SHIFT else "get_mapped_directory"
                    for stage in ("resolve", "exists", "shell"):
                        with self.subTest(mod=mod, stage=stage):
                            entered, release = threading.Event(), threading.Event()
                            calls, threads, timed_out = [], [], []
                            def gate(threads=threads, entered=entered, release=release, timed_out=timed_out):
                                threads.append(threading.get_ident())
                                entered.set()
                                if not release.wait(5):
                                    timed_out.append(True)
                            def resolve(*args, stage=stage, gate=gate, calls=calls):
                                if stage == "resolve":
                                    gate()
                                calls.append("resolve")
                                return str(data)
                            def exists(path, stage=stage, gate=gate, calls=calls):
                                if stage == "exists":
                                    gate()
                                calls.append("exists")
                                return True
                            def shell(*args, stage=stage, gate=gate, calls=calls):
                                if stage == "shell":
                                    gate()
                                calls.append("shell")
                            queue = ckit.JobQueue.defaultQueue()
                            text = 'outer;  "input arg" one;two  '
                            self.window.commandline_history.clear()
                            with (patch.object(clnch_commandexecutor, helper, side_effect=resolve),
                                  patch.object(clnch_commandexecutor.os.path, "isdir", side_effect=exists),
                                  patch.object(clnch_commandexecutor, "shellExecute", side_effect=shell),
                                  patch.object(self.window, "inactivate") as inactivate):
                                try:
                                    self.input_action(text, lambda mod=mod: self.key(ckit.VK_RETURN, mod))
                                    self.assertEqual(self.window.commandline_history, [text])
                                    self.pump(entered.is_set)
                                    queue.enqueue(ckit.JobItem(lambda job, calls=calls: calls.append("next"), None))
                                    def next_input(threads=threads, queue=queue, calls=calls,
                                                   release=release, timed_out=timed_out):
                                        self.assertEqual(self.window.commandline_edit.getText(), "next input")
                                        self.assertEqual(threads, [queue.ident])
                                        self.assertNotEqual(queue.ident, owner)
                                        self.assertNotIn("next", calls)
                                        self.assertFalse(release.is_set())
                                        self.assertEqual(timed_out, [])
                                    self.input_action("next input", next_input)
                                    inactivate.assert_not_called()
                                finally:
                                    release.set()
                                    self.pump(lambda queue=queue: queue.numItems() == 0)
                                self.assertEqual(calls, ["resolve", "exists", "shell", "next"])
                                self.assertEqual(timed_out, [])
                                self.assertEqual(self.window.commandline_history, [text])
                                inactivate.assert_not_called()

            def test_real_app_paths_registry_and_os_execution(self):
                name = "recraft-test-" + uuid.uuid4().hex
                subkey = clnch_commandplatform._APP_PATHS_KEY + "\\" + name + ".exe"
                with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, subkey, 0,
                                        winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as key:
                    winreg.SetValueEx(key, "", 0, winreg.REG_EXPAND_SZ, '"' + str(pythonw) + '"')
                try:
                    self.assertEqual(clnch_commandplatform.resolve_system_executable(name), str(pythonw))
                    import clnch_commandexecutor
                    self.apply({"alias": {"target": {"link": "child"}},
                                "child": {"target": {"link": name}}})
                    self.window.modifier_settings.update(CTRL_ACTION="mapped_folder",
                        SOURCE_ROOTS=(str(pythonw.parent),), CTRL_DESTINATION_ROOT=str(data))
                    with patch.object(clnch_commandexecutor, "shellExecute") as opened:
                        self.invoke("alias", mod=ckit.MODKEY_SHIFT)
                        self.pump(lambda: ckit.JobQueue.defaultQueue().numItems() == 0)
                        opened.assert_called_once_with(None, str(pythonw.parent), "", "")
                        opened.reset_mock()
                        self.invoke("alias", mod=ckit.MODKEY_CTRL)
                        self.pump(lambda: ckit.JobQueue.defaultQueue().numItems() == 0)
                        opened.assert_called_once_with(None, str(data), "", "")
                    output = data / "app-paths.json"
                    text = name + ";" + subprocess.list2cmdline(["-B", "-S", str(probe), str(output), "OS argument"])
                    line = SimpleNamespace(planCommand=lambda command, info, text: command(info), quit=lambda: None)
                    self.assertTrue(self.window.commandline_list[1].onEnter(line, text, 0))
                    self.assertEqual(self.result(output)["args"], ["OS argument"])
                finally:
                    winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, subkey, winreg.KEY_WOW64_64KEY)

            def run_editor(self, operation, *, target=None, dropped_files=None, shown=None, entry=None, parent=None):
                was_enabled = self.window.isEnabled()
                errors = []
                original = clnch_cmdeditor.CommandEditor
                def create(*args, **kwargs):
                    editor = original(*args, **kwargs)
                    def drive():
                        editor.killTimer(drive)
                        try:
                            self.assertFalse(self.window.isEnabled())
                            operation(editor)
                        except BaseException as error:  # noqa: BLE001  # Surface callback failures and close the native modal loop.
                            errors.append(error)
                            editor._on_cancel()
                    editor.setTimer(drive, 30)
                    return editor
                with patch.object(clnch_cmdeditor, "CommandEditor", side_effect=create):
                    result = (entry() if entry else
                              self.ui._open_command_editor(target, dropped_files, shown, parent_window=parent))
                self.assertEqual(errors, [])
                self.assertEqual(self.window.isEnabled(), was_enabled)
                return result

            def test_native_drop_folder_file_names_and_edited_fields(self):
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
                kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
                kernel32.GlobalLock.argtypes = (wintypes.HGLOBAL,)
                kernel32.GlobalLock.restype = ctypes.c_void_p
                kernel32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
                user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
                def drop(window, files):
                    # DROPFILES with client coordinates (0, 0) and a UTF-16 path list.
                    payload = bytes((wintypes.DWORD * 5)(20, 0, 0, 1, 1))
                    payload += ("\0".join(map(str, files)) + "\0\0").encode("utf-16-le")
                    handle = kernel32.GlobalAlloc(2, len(payload))
                    self.assertTrue(handle)
                    pointer = kernel32.GlobalLock(handle)
                    self.assertTrue(pointer)
                    ctypes.memmove(pointer, payload, len(payload))
                    kernel32.GlobalUnlock(handle)
                    user32.SendMessageW(window.getHWND(), 0x0233, handle, 0)

                folder = data / "my.folder"
                folder.mkdir()
                file = folder / "My;\u00a0\u3000File.exe"
                file.touch()
                before = (data / "commands.json").read_bytes()
                for path, name, workdir in ((folder, "my.folder", folder), (file, "MyFile", folder)):
                    with self.subTest(path=path):
                        def inspect(editor, path=path, name=name, workdir=workdir):
                            self.assertEqual(editor.edit_by_id["name"].getText(), name)
                            self.assertEqual(editor.edit_by_id["link"].getText(), str(path))
                            self.assertEqual(editor.edit_by_id["workdir"].getText(), str(workdir))
                            manual = " Manual;\u3000Name "
                            editor.edit_by_id["name"].setText(manual)
                            editor.edit_by_id["workdir"].setText(str(data))
                            editor.edit_by_id["args"].setText("--keep")
                            drop(editor, [file])
                            self.assertEqual(editor.edit_by_id["name"].getText(), manual)
                            self.assertEqual(editor.edit_by_id["workdir"].getText(), str(data))
                            self.assertEqual(editor.edit_by_id["args"].getText(), "--keep")
                            self.key(ckit.VK_ESCAPE, window=editor)
                        self.assertIsNone(self.run_editor(inspect, entry=lambda path=path: drop(self.window, [path])))
                        self.assertEqual((data / "commands.json").read_bytes(), before)

            def test_native_list_close_cancels_config_font_and_command_actions(self):
                import clnch_listwindow

                self.apply({"alpha": {}, "beta": {}})
                before = (data / "commands.json").read_bytes()
                init = clnch_listwindow.ListWindow.__init__
                handles, errors, results = [], [], []
                def created(listing, *args, **kwargs):
                    init(listing, *args, **kwargs)
                    handles.append(listing.getHWND())
                    def drive():
                        listing.killTimer(drive)
                        try:
                            self.key(ckit.VK_END, window=listing)
                            if mode == "filtered":
                                self.key(ckit.VK_F, ckit.MODKEY_CTRL, window=listing)
                                user32.SendMessageW(listing.getHWND(), 0x0102, ord("b"), 1)
                            if mode == "system_close":
                                user32.SendMessageW(listing.getHWND(), 0x0112, 0xF060, 0)
                            elif mode in ("wm_close", "filtered"):
                                user32.SendMessageW(listing.getHWND(), 0x0010, 0, 0)
                            else:
                                self.key(ckit.VK_RETURN if mode == "enter" else ckit.VK_ESCAPE, window=listing)
                            results.append(listing.getResult())
                            self.assertEqual(clnch_listwindow._split_list_result(results[-1])[0],
                                             len(listing.items) - 1 if mode == "enter" else -1)
                        except BaseException as error:  # noqa: BLE001  # Surface timer failures and close the native modal loop.
                            errors.append(error)
                            listing.cancel()
                    listing.setTimer(drive, 30)

                with patch.object(clnch_listwindow.ListWindow, "__init__", created):
                    for mode in ("wm_close", "system_close", "escape", "enter"):
                        with self.subTest(mode=mode):
                            clnch_ini.set("MISC", "auto_complete", "0")
                            clnch_configmenu._configAutoComplete(self.window)
                            self.assertEqual(clnch_ini.get("MISC", "auto_complete"), "1" if mode == "enter" else "0")
                            clnch_ini.set("FONT", "name", "MS Gothic")
                            with (patch.object(self.window, "enumFonts", return_value=["MS Gothic", "Consolas"]),
                                  patch.object(self.window, "updateFont") as update):
                                clnch_configmenu._configFontName(self.window)
                            self.assertEqual(clnch_ini.get("FONT", "name"), "Consolas" if mode == "enter" else "MS Gothic")
                            self.assertEqual(update.call_count, int(mode == "enter"))
                            edited, saved = [], []
                            def edit(name, parent_window, edited=edited, mode=mode):
                                edited.append(name)
                                raise RuntimeError("explicit edit" if mode == "enter" else "unexpected edit")
                            if mode == "enter":
                                # End the list after checking the explicit Enter handoff.
                                with self.assertRaisesRegex(RuntimeError, "explicit edit"):
                                    clnch_cmdlist.open_list(self.window, on_edit=edit, on_saved=lambda saved=saved: saved.append(True))
                            else:
                                clnch_cmdlist.open_list(self.window, on_edit=edit, on_saved=lambda saved=saved: saved.append(True))
                            self.assertEqual(edited, ["beta"] if mode == "enter" else [])
                            self.assertEqual(saved, [])
                            self.assertTrue(self.window.isEnabled())
                    mode = "filtered"
                    edited.clear()
                    clnch_cmdlist.open_list(self.window, on_edit=edit)
                    self.assertEqual(edited, [])
                self.assertEqual(errors, [])
                self.assertEqual(len(results), 13)
                self.assertEqual((data / "commands.json").read_bytes(), before)
                user32.IsWindow.argtypes = (wintypes.HWND,)
                self.assertTrue(all(not user32.IsWindow(handle) for handle in handles))

            def test_native_onekey_search_with_empty_display_rows(self):
                import clnch_listwindow

                child = clnch_listwindow.ListWindow(200, 200, 5, 1, 30, 8, self.window,
                    False, "empty labels", ["", ("alpha", "a"), ("", "empty"), ["alpine", "b"], "beta"],
                    initial_select=1, onekey_search=True, onekey_decide=True, return_modkey=True)
                try:
                    with redirect_stderr(io.StringIO()) as errors, patch.object(child, "quit", wraps=child.quit) as quit_list:
                        for expected in (3, 1, 3):
                            user32.SendMessageW(child.getHWND(), 0x0102, ord("a"), 1)
                            self.assertEqual(child.select, expected)
                        user32.SendMessageW(child.getHWND(), 0x0102, ord("z"), 1)
                        quit_list.assert_not_called()
                        user32.SendMessageW(child.getHWND(), 0x0102, ord("b"), 1)
                        self.assertEqual(child.getResult(), (4, 0))
                        quit_list.assert_called_once_with()
                    self.assertEqual(errors.getvalue(), "")
                finally:
                    child.destroy()

            def test_native_json_gui_changes_keep_custom_positions_and_dispatch(self):
                output = data / "priority-child.json"
                self.apply({"tool": {"target": self.probe_action(output)},
                            "alias": {"target": {"link": "tool"}},
                            "history": {"target": self.probe_action(output)},
                            "head-alias": {"target": {"link": "history"}}})
                custom_path = data / "custom.py"
                template = (
                    'def configure(window):\n'
                    '    window.priority_runs = getattr(window, "priority_runs", 0) + 1\n'
                    '    window.priority_calls = []\n'
                    '    def head(info): window.priority_calls.append(("head", list(info.args)))\n'
                    '    def middle(info): window.priority_calls.append(("middle", list(info.args)))\n'
                    '    def tail(info): window.priority_calls.append(("tail", list(info.args)))\n'
                    '    window.launcher.command_list.insert(0, ("history", head))\n'
                    '    index = next(i for i, item in enumerate(window.launcher.command_list) if item[0] == "alias")\n'
                    '    window.launcher.command_list.insert(index, ("middle", middle))\n'
                    '    window.launcher.command_list.append(("TOOL", tail))\n')
                custom_path.write_text(template, encoding="utf-8")
                self.window.configure()
                self.ui = self.window.cmd_keymap["F12"].__self__
                head, middle, tail = [item for item in self.window.launcher.command_list
                                      if type(item) is tuple]

                def check_custom(*, dispatch=True):
                    items = self.window.launcher.command_list
                    self.assertIs(items[0], head)
                    self.assertIs(items[-1], tail)
                    self.assertIs(items[items.index(middle) + 1], self.ui.registry._json["alias"])
                    self.assertEqual(self.window.priority_runs, 1)
                    if dispatch:
                        for name, label in (("HiStOrY", "head"), ("middle", "middle")):
                            self.input_action(name + ";arg", lambda: self.key(ckit.VK_RETURN))
                            self.assertEqual(self.window.priority_calls[-1], (label, ["arg"]))

                check_custom()
                before = self.window.priority_calls.copy()
                self.input_action("head-alias", lambda: self.key(ckit.VK_RETURN))
                self.assertEqual(self.result(output)["args"], [])
                self.assertEqual(self.window.priority_calls, before)
                output.unlink()
                for argument in ("updated", "updated-again"):
                    previous = self.ui.registry._json["tool"]
                    def edit(editor, argument=argument):
                        editor.edit_by_id["args"].setText(self.probe_action(output)["args"] + " " + argument)
                        self.key(ckit.VK_RETURN, window=editor)
                    self.assertEqual(self.run_editor(edit, target="tool"), "tool")
                    self.assertFalse(any(item is previous for item in self.window.launcher.command_list))
                    check_custom()
                    for name in ("ToOl", "alias"):
                        self.input_action(name, lambda: self.key(ckit.VK_RETURN))
                        self.assertEqual(self.result(output)["args"], [argument])
                        output.unlink()

                original = clnch_cmdlist.CommandListWindow
                failures, stages = [], []
                def create(*args, **kwargs):
                    listing = original(*args, **kwargs)
                    stage = len(stages)
                    stages.append(stage)
                    def drive():
                        listing.killTimer(drive)
                        try:
                            check_custom(dispatch=False)
                            if stage < 2:
                                listing.select = next(i for i, item in enumerate(listing.items) if item[1] == "tool")
                                self.key(ckit.VK_INSERT if stage == 0 else ckit.VK_DELETE,
                                         2 if stage == 0 else 0, window=listing)
                            else:
                                self.key(ckit.VK_ESCAPE, window=listing)
                        except BaseException as error:  # noqa: BLE001  # Surface timer assertions and leave the native modal loop.
                            failures.append(error)
                            listing.cancel()
                    listing.setTimer(drive, 30)
                    return listing
                with patch.object(clnch_cmdlist, "CommandListWindow", side_effect=create), \
                     patch.object(clnch_cmdlist, "_confirm_delete", return_value=True):
                    clnch_cmdlist.open_list(self.window, on_saved=self.ui.reload_commands)
                self.assertEqual(failures, [])
                self.assertEqual(stages, [0, 1, 2])
                check_custom()
                self.assertIn("tool_copy_1", self.ui.registry._json)
                self.assertIsNone(self.ui.registry.get_handler("tool"))
                self.assertEqual(self.ui.registry.resolve_path("alias"), "tool")
                self.input_action("tool;fallback", lambda: self.key(ckit.VK_RETURN))
                self.assertEqual(self.window.priority_calls[-1], ("tail", ["fallback"]))

                custom_path.write_text(template.replace('insert(0, ', 'append('), encoding="utf-8")
                self.window.command_Reload(None)
                self.ui = self.window.cmd_keymap["F12"].__self__
                self.assertFalse(self.window._config_failed)
                self.assertEqual(self.window.priority_runs, 2)
                items = self.window.launcher.command_list
                self.assertIs(items[0][1], self.ui.registry.get_handler("history"))
                self.assertEqual(items[-2][0], "history")
                self.assertFalse(any(item is old for item in items for old in (head, middle, tail)))
                self.ui.reload_commands()
                self.assertEqual(self.window.launcher.command_list[-2:], items[-2:])
                self.assertEqual(self.window.priority_runs, 2)

            def test_native_editor_save_cancel_drop_and_custom_retention(self):
                def save(editor):
                    editor.edit_by_id["name"].setText("saved")
                    editor.edit_by_id["link"].setText(str(probe))
                    editor._on_keydown(ckit.VK_RETURN, 0)
                self.assertEqual(self.run_editor(save), "saved")
                self.assertIn("saved", dict(self.window.launcher.command_list))
                self.assertEqual(self.window.custom_runs, 1)
                self.invoke("customonly", ["retained"])
                self.assertEqual(self.window.custom_args, ["retained"])
                before = (data / "commands.json").read_bytes()
                self.assertIsNone(self.run_editor(lambda editor: editor._on_keydown(ckit.VK_ESCAPE, 0), target="saved"))
                self.assertEqual((data / "commands.json").read_bytes(), before)
                def dropped(editor):
                    self.assertEqual(editor.edit_by_id["link"].getText(), str(probe))
                    editor._on_keydown(ckit.VK_ESCAPE, 0)
                self.run_editor(dropped, dropped_files=[str(probe)])

            def test_native_editor_modifiers_validation_failed_save_and_retry(self):
                self.apply({"old": {"target": {"link": str(probe)}}, "taken": {}})
                path = data / "commands.json"
                before = path.read_bytes()
                expected, messages = {}, []
                def edit(editor):
                    self.assertEqual(editor.edit_by_id["name"].getSelection(), [0, 3])
                    editor.edit_by_id["name"].setText("TAKEN")
                    for index, key in enumerate(clnch_cmdeditor.MODIFIER_KEYS):
                        self.key(key, 1, window=editor)
                        self.assertEqual(editor.draft.modifier_index, index)
                        self.assertEqual(editor.focus_index, 5)
                        values = {"link": str(probe), "args": f"--modifier {index}",
                                  "workdir": str(data), "view_mode": clnch_cmdeditor.VIEW_MODES[index % 3]}
                        for field in ("link", "args", "workdir"):
                            editor.edit_by_id[field].setText(values[field])
                        self.key(clnch_cmdeditor.VIEW_KEYS[index % 3], 1, window=editor)
                        expected[clnch_cmdeditor.MODIFIERS[index]] = values
                    with patch.object(editor, "_show_error", side_effect=lambda *args: messages.append(args)):
                        self.assertFalse(editor._save())
                        self.assertEqual(messages[-1], (strings.ERROR_INPUT_TITLE, strings.COMMAND_DUPLICATE))
                        editor.edit_by_id["name"].setText("Renamed")
                        editor.edit_by_id["link"].setText("")
                        self.assertFalse(editor._save())
                        self.assertEqual(messages[-1], (strings.ERROR_INPUT_TITLE,
                            strings.MODIFIER_LINK_REQUIRED.format(modifier=clnch_cmdeditor.MODIFIER_LABELS[3])))
                        editor.edit_by_id["link"].setText(str(probe))
                        with patch.object(clnch_cmdstore.os, "replace", side_effect=PermissionError("locked")):
                            self.assertFalse(editor._save())
                        self.assertEqual(messages[-1], (strings.ERROR_SAVE_TITLE,
                            strings.COMMAND_SAVE_ERROR.format(error="locked")))
                    self.assertFalse(editor.result_saved)
                    self.assertEqual(path.read_bytes(), before)
                    for index, key in enumerate(clnch_cmdeditor.MODIFIER_KEYS):
                        self.key(key, 1, window=editor)
                        for field in ("link", "args", "workdir"):
                            text = expected[clnch_cmdeditor.MODIFIERS[index]][field]
                            self.assertEqual(editor.edit_by_id[field].getText(), text)
                            self.assertEqual(editor.edit_by_id[field].getSelection(), [len(text), len(text)])
                        self.assertEqual(editor.view_choice.getValue(), index % 3)
                    self.key(ckit.VK_RETURN, window=editor)
                with patch.object(self.ui, "reload_commands", wraps=self.ui.reload_commands) as reload_commands:
                    self.assertEqual(self.run_editor(edit, target="old"), "renamed")
                reload_commands.assert_called_once_with()
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"renamed": expected, "taken": {}})
                self.assertNotIn("old", dict(self.window.launcher.command_list))
                self.assertIn("renamed", dict(self.window.launcher.command_list))
                self.assertEqual(self.window.custom_runs, 1)

            def test_native_command_names_zero_actions_and_invalid_reload(self):
                self.apply({"old": {"target": {"link": str(probe)}}, "about": {},
                            "alias": {"target": {"link": "about"}}, "": {}})
                path = data / "commands.json"
                before = path.read_bytes()
                for target in (None, "old"):
                    def invalid(editor):
                        for name in ("bad;name", " foo", "foo ", "foo bar", "foo\tbar", "foo　bar"):
                            editor.edit_by_id["name"].setText(name)
                            with patch.object(editor, "_show_error") as error:
                                self.assertFalse(editor._save())
                                error.assert_called_once_with(strings.ERROR_INPUT_TITLE,
                                    strings.COMMAND_NAME_ERROR.format(name=name))
                            self.assertEqual(editor.edit_by_id["name"].getText(), name)
                            self.assertEqual(editor.draft.name, name)
                            self.assertEqual(path.read_bytes(), before)
                        self.key(ckit.VK_ESCAPE, window=editor)
                    self.assertIsNone(self.run_editor(invalid, target=target))
                def save_empty(editor):
                    editor.edit_by_id["name"].setText("disabled")
                    self.key(ckit.VK_RETURN, window=editor)
                self.assertEqual(self.run_editor(save_empty), "disabled")
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["disabled"], {})
                output = io.StringIO()
                with patch.object(self.window, "ShellExecuteCommand") as shell, redirect_stderr(output), contextlib.redirect_stdout(output):
                    for name in ("about", "alias", "disabled", ""):
                        self.invoke(name)
                    shell.assert_not_called()
                self.assertEqual(output.getvalue(), "")
                previous = self.window.launcher.command_list
                previous_custom = self.window.custom
                path.write_text('{"bad;name": {}}', encoding="utf-8")
                with redirect_stderr(io.StringIO()) as errors:
                    self.window.command_Reload(None)
                self.assertIn("bad;name", errors.getvalue())
                self.assertIs(self.window.launcher.command_list, previous)
                self.assertIs(self.window.custom, previous_custom)
                def blocked(editor):
                    with patch.object(editor, "_show_error") as error:
                        self.assertFalse(editor._save())
                        error.assert_called_once_with(strings.ERROR_LOAD_TITLE,
                            strings.COMMAND_LOAD_BLOCKED.format(error=editor.load_error))
                    self.key(ckit.VK_ESCAPE, window=editor)
                self.assertIsNone(self.run_editor(blocked, target="old"))
                self.assertEqual(path.read_text(encoding="utf-8"), '{"bad;name": {}}')

            def test_native_duplicate_json_names_block_list_and_editor_save(self):
                import clnch_msgbox

                self.apply({"old": {"target": {"link": str(probe)}}})
                path = data / "commands.json"
                for second in ("Tool", "tool"):
                    with self.subTest(second=second):
                        path.write_text('{"Tool": {"target": {"link": "first.exe"}}, '
                                        '"' + second + '": {"target": {"link": "last.exe"}}}', encoding="utf-8")
                        before = path.read_bytes()
                        error = strings.COMMAND_NAME_DUPLICATE.format(first="Tool", second=second)
                        messages = []
                        def acknowledge(box, messages=messages):
                            messages.append((box.title, box.message))
                            self.key(ckit.VK_RETURN, window=box)
                            self.assertEqual(box.getResult(), clnch_msgbox.MSGBOX_RESULT_OK)
                        with patch.object(clnch_msgbox.MessageBox, "messageLoop", acknowledge):
                            with patch.object(clnch_cmdlist, "CommandListWindow") as listing:
                                clnch_cmdlist.open_list(self.window)
                            listing.assert_not_called()
                            self.assertEqual(messages[-1], (strings.ERROR_TITLE,
                                strings.COMMAND_LOAD_ERROR.format(error=error)))
                            for target in (None, "tool"):
                                def blocked(editor, error=error, messages=messages, before=before):
                                    self.assertEqual(editor.load_error, error)
                                    editor.edit_by_id["name"].setText("new")
                                    editor.edit_by_id["link"].setText("notepad.exe")
                                    self.key(ckit.VK_RETURN, window=editor)
                                    self.assertEqual(messages[-1], (strings.ERROR_LOAD_TITLE,
                                        strings.COMMAND_LOAD_BLOCKED.format(error=error)))
                                    self.assertFalse(editor.result_saved)
                                    self.assertFalse(editor.commands_changed)
                                    self.assertTrue(editor.isEnabled())
                                    self.assertEqual(editor.edit_by_id["name"].getText(), "new")
                                    self.assertEqual(editor.edit_by_id["link"].getText(), "notepad.exe")
                                    self.assertEqual(path.read_bytes(), before)
                                    self.key(ckit.VK_ESCAPE, window=editor)
                                with patch.object(clnch_cmdeditor, "save_commands") as save:
                                    self.assertIsNone(self.run_editor(blocked, target=target))
                                save.assert_not_called()
                        self.assertEqual(len(messages), 3)
                        self.assertTrue(self.window.isEnabled())
                        self.assertEqual(path.read_bytes(), before)

            def test_native_json_reload_preserves_live_configuration_and_recovers(self):
                path = data / "commands.json"
                output_path = data / "reload-retained-command.json"
                self.apply({"old": {"target": self.probe_action(output_path)},
                            "alias": {"target": {"link": "old"}}})
                released, keys = [], []
                resource = ckit.TextWindow(show=False)
                hwnd = resource.getHWND()
                user32.IsWindow.argtypes = (wintypes.HWND,)
                def cleanup():
                    resource.destroy()
                    released.append("old")
                self.window.registerConfigCleanup(cleanup)
                self.window.keymap["F8"] = lambda info: keys.append("old")
                attributes = ("custom", "keymap", "cmd_keymap", "commandline_list", "association_list",
                              "input_settings", "modifier_settings", "altenter_settings", "command_drop_handler",
                              "_config_cleanup")
                previous = {name: getattr(self.window, name) for name in attributes}
                commands = self.window.launcher.command_list
                namespace = ckit.ckit_userconfig.user_namespace
                custom_module = sys.modules["custom"]
                custom_path = data / "custom.py"
                custom_path.write_text('raise AssertionError("must not load before JSON validation")\n', encoding="utf-8")
                for contents in ('{broken', '{"bad": {"unknown": {}}}',
                                 '{"tool": {"target": {"link": "first.exe"}}, "tool": {"target": {"link": "last.exe"}}}',
                                 '{"Tool": {"target": {"link": "first.exe"}}, "tool": {"target": {"link": "last.exe"}}}',
                                 '{"bad": {"target": {"link": "x", "unknown": "x"}}}',
                                 '{"bad": {"target": {"link": 1}}}', '{"bad;name": {}}',
                                 *(json.dumps({name: {}}) for name in (" foo", "foo ", " foo ", "foo bar", "foo \u00a0bar",
                                         "foo\tbar", "foo\nbar", "foo\u3000bar", " \u00a0 ")), "io-error"):
                    with self.subTest(contents=contents):
                        if contents == "io-error":
                            path.unlink()
                            path.mkdir()
                        else:
                            path.write_text(contents, encoding="utf-8")
                        with redirect_stderr(io.StringIO()) as errors, contextlib.redirect_stdout(io.StringIO()) as output:
                            self.assertIsNone(self.window.command_Reload(None))
                        self.assertIn("Error", errors.getvalue())
                        self.assertNotIn("must not load", errors.getvalue())
                        self.assertNotIn(strings.CONFIG_RELOADED, output.getvalue())
                        self.assertIs(self.window.launcher.command_list, commands)
                        for name, value in previous.items():
                            self.assertIs(getattr(self.window, name), value, name)
                        self.assertIs(ckit.ckit_userconfig.user_namespace, namespace)
                        self.assertIs(sys.modules["custom"], custom_module)
                        self.assertEqual(released, [])
                        self.assertTrue(user32.IsWindow(hwnd))
                        self.assertEqual(self.window.custom_runs, 1)
                        self.invoke("customonly", [contents])
                        self.assertEqual(self.window.custom_args, [contents])
                        self.input_action("retained", lambda: self.key(ckit.VK_F8))
                        self.assertEqual(keys[-1], "old")
                        self.invoke("alias", [contents])
                        self.assertEqual(self.result(output_path)["args"], [contents])
                        output_path.unlink()
                        if contents == "io-error":
                            path.rmdir()
                        else:
                            self.assertEqual(path.read_text(encoding="utf-8"), contents)

                # Change the file during cleanup: application must use the validated snapshot.
                self.window.registerConfigCleanup(lambda: path.write_text("{changed after validation", encoding="utf-8"))
                custom_path.write_text("", encoding="utf-8")
                path.write_text(json.dumps({"updated": {"target": self.probe_action(output_path)}}), encoding="utf-8")
                with patch.object(clnch_mainwindow, "load_commands", wraps=clnch_cmdstore.load_commands) as load, \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    self.window.command_Reload(None)
                load.assert_called_once()
                self.assertEqual(output.getvalue().count(strings.CONFIG_RELOADED), 1)
                self.assertEqual(released, ["old"])
                self.assertFalse(user32.IsWindow(hwnd))
                self.assertNotIn("old", dict(self.window.launcher.command_list))
                self.assertNotIn("customonly", dict(self.window.launcher.command_list))
                self.invoke("updated", ["new"])
                self.assertEqual(self.result(output_path)["args"], ["new"])

                for contents in ("{}", '{"about": {}, "disabled": {}, "alias": {"target": {"link": "about"}}}', None):
                    with self.subTest(valid=contents):
                        if contents is None:
                            path.unlink()
                        else:
                            path.write_text(contents, encoding="utf-8")
                        with contextlib.redirect_stdout(io.StringIO()) as output:
                            self.window.command_Reload(None)
                        self.assertEqual(output.getvalue().count(strings.CONFIG_RELOADED), 1)
                        self.assertNotIn("updated", dict(self.window.launcher.command_list))
                        self.assertIn("reload", dict(self.window.launcher.command_list))
                        if contents is not None and "disabled" in contents:
                            with patch.object(self.window, "ShellExecuteCommand") as shell:
                                for name in ("about", "disabled", "alias"):
                                    self.invoke(name)
                            shell.assert_not_called()
                        self.assertEqual(path.exists(), contents is not None)

            def test_native_editor_unchanged_and_load_failure_skip_save_and_reload(self):
                self.apply(clnch_cmdstore.normalize_commands({"tool": {"target": {"link": str(probe)}}}))
                path = data / "commands.json"
                before = path.read_bytes()
                with patch.object(self.ui, "reload_commands", wraps=self.ui.reload_commands) as reload_commands:
                    with patch.object(clnch_cmdstore.tempfile, "NamedTemporaryFile", side_effect=AssertionError("unexpected write")):
                        self.assertEqual(self.run_editor(lambda editor: self.key(ckit.VK_RETURN, window=editor),
                                                         target="tool"), "tool")
                    self.assertEqual(path.read_bytes(), before)
                    path.write_text("{broken", encoding="utf-8")
                    def blocked(editor):
                        editor.edit_by_id["link"].setText("draft.exe")
                        with patch.object(editor, "_show_error") as error:
                            self.assertFalse(editor._save())
                            error.assert_called_once_with(strings.ERROR_LOAD_TITLE,
                                strings.COMMAND_LOAD_BLOCKED.format(error=editor.load_error))
                        self.assertEqual(editor.edit_by_id["link"].getText(), "draft.exe")
                        self.key(ckit.VK_ESCAPE, window=editor)
                    self.assertIsNone(self.run_editor(blocked, target="tool"))
                reload_commands.assert_not_called()
                self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

            def test_native_new_and_ctrl_e_input_entries(self):
                def save(editor):
                    self.assertIsNone(editor.draft.target_name)
                    editor.edit_by_id["name"].setText("from-new")
                    editor.edit_by_id["link"].setText(str(probe))
                    editor._on_keydown(ckit.VK_RETURN, 0)
                self.run_editor(save, entry=lambda: self.input_action("new", lambda: self.key(ckit.VK_RETURN)))
                self.assertIn("from-new", dict(self.window.launcher.command_list))
                def cancel(editor):
                    self.assertEqual(editor.draft.target_name, "from-new")
                    editor._on_keydown(ckit.VK_ESCAPE, 0)
                self.run_editor(cancel,
                    entry=lambda: self.input_action("from-new;arg", lambda: self.key(ord("E"), 2)))
                self.assertEqual(self.window.custom_runs, 1)

            def test_native_list_modifier_tuple_search_and_config(self):
                import clnch_listwindow
                child = clnch_cmdlist.CommandListWindow(
                    200, 200, 5, 1, 30, 8, self.window, False, "tuple search",
                    [("alpha", "alpha"), ("target", "target"), ("target last", "target_last")], return_modkey=True)
                try:
                    self.key(ckit.VK_F, 2, window=child)
                    for ch in "target":
                        user32.SendMessageW(child.getHWND(), 0x0102, ord(ch), 1)
                    self.key(ckit.VK_END, window=child)
                    child.result_mod = 4
                    self.assertEqual(child.getResult(), (2, 4))
                    for ch in "missing":
                        user32.SendMessageW(child.getHWND(), 0x0102, ord(ch), 1)
                    self.assertEqual(child.getResult(), (-1, 4))
                    self.key(ckit.VK_ESCAPE, window=child)
                    self.key(ckit.VK_ESCAPE, window=child)
                    self.assertEqual(child.getResult(), (-1, 0))
                finally:
                    child.destroy()
                original = clnch_listwindow.ListWindow
                errors, handles = [], []
                for selected, expected in ((1, "1"), (-1, "1"), (0, "0")):
                    def create(*args, **kwargs):
                        listing = original(*args, **kwargs)
                        listing.return_modkey = True
                        handles.append(listing.getHWND())
                        def drive():
                            listing.killTimer(drive)
                            try:
                                if selected < 0:  # noqa: B023  # Timer completes before the next selected value.
                                    self.key(ckit.VK_ESCAPE, window=listing)
                                else:
                                    self.key(ckit.VK_HOME, window=listing)
                                    for _ in range(selected):  # noqa: B023  # Timer completes before the next selected value.
                                        self.key(ckit.VK_DOWN, window=listing)
                                    self.key(ckit.VK_RETURN, window=listing)
                            except BaseException as error:  # noqa: BLE001  # Surface timer failures after closing the isolated native loop.
                                errors.append(error)
                                listing.cancel()
                        listing.setTimer(drive, 30)
                        return listing
                    with patch.object(clnch_listwindow, "ListWindow", side_effect=create):
                        clnch_configmenu._configAutoComplete(self.window)
                    self.assertEqual(clnch_ini.get("MISC", "auto_complete"), expected)
                    self.assertTrue(self.window.isEnabled())
                self.assertEqual(errors, [])
                self.assertTrue(all(not user32.IsWindow(handle) for handle in handles))

            def test_native_list_status_optional_state_and_replacement(self):
                import clnch_listwindow
                import clnch_statusbar

                child = clnch_listwindow.ListWindow(
                    0, 0, 20, 2, 40, 10, self.window, show=False,
                    title="status test", items=["item"],
                    statusbar_handler=lambda width, select: "one\ntwo",
                )
                try:
                    layer = child.status_bar_layer
                    self.assertIsNotNone(layer)
                    assert layer is not None
                    replacement = clnch_statusbar.SimpleStatusBarLayer()
                    calls = []
                    def handler(width, select):
                        calls.append((width, select))
                        child.status_bar_layer = replacement
                        return "one\ntwo"
                    child.statusbar_handler = handler
                    with patch.object(replacement, "setMessage", wraps=replacement.setMessage) as messages:
                        child.paint()
                        self.assertEqual([call.args for call in messages.call_args_list], [("one",), ("two",)])
                    self.assertEqual(calls, [(child.width(), 0)])
                    self.assertIs(child.status_bar_layer, replacement)
                    child.statusbar_handler = None
                    with self.assertRaisesRegex(TypeError, "'NoneType' object is not callable"):
                        child.paint()
                    child.isearch = clnch_listwindow.clnch_isearch.IncrementalSearch()
                    child.isearch.isearch_value = "q"
                    child.paint()
                    self.assertEqual(replacement.message, clnch_listwindow.strings.LIST_SEARCH.format(query="q"))
                    child.isearch = None
                    child.statusbar_handler = lambda width, select: ""
                    child.status_bar_layer = None
                    child.paint()  # No lines means no layer operation.
                    child.statusbar_handler = lambda width, select: "message"
                    with self.assertRaises(AttributeError) as raised:
                        child.paint()
                    self.assertEqual(str(raised.exception), "'NoneType' object has no attribute 'setMessage'")
                    self.assertEqual(raised.exception.name, "setMessage")
                    self.assertIsNone(raised.exception.obj)
                    child.status_bar = None
                    child.statusbar_handler = None
                    with patch.object(child, "setTitle", wraps=child.setTitle) as title:
                        child.paint()
                        title.assert_called_once_with("status test")
                finally:
                    child.destroy()

            def test_native_rgb_blending(self):
                from ckit import ckit_theme
                edit = ckit.EditWidget(self.window, 0, 0, 20, 1, "rgb input", [0, 3])
                try:
                    for theme, expected in (("black", (191, 191, 191)), ("gray", (189, 191, 193)), ("white", (63, 63, 63))):
                        ckit.setTheme(theme, {})
                        self.assertEqual(ckit.getHintColor(), expected)
                        edit.paint()
                        parser = ckit_theme.ini
                        assert parser is not None
                        for key in ("fg", "bg"):
                            value = parser.get("COLOR", key)
                            parser.set("COLOR", key, "invalid RGB")
                            try:
                                self.assertIsNone(ckit.getColor(key))
                                for operation in (ckit.getHintColor, edit.paint):
                                    with self.assertRaisesRegex(TypeError, "^'NoneType' object is not iterable$"):
                                        operation()
                            finally:
                                parser.set("COLOR", key, value)
                        self.assertEqual(edit.getText(), "rgb input")
                        self.assertEqual(edit.getSelection(), [0, 3])
                finally:
                    edit.destroy()

            def test_native_optional_text_and_prepared_candidate_contracts(self):
                ckit.TextWidget.updateColor()
                text = ckit.TextWidget(self.window, 0, 0, 30, 5)
                edit = ckit.EditWidget(self.window, 0, 0, 20, 1, "a", auto_complete=-7,
                                       candidate_handler=lambda info: (["alpha", "alpine"], 0))
                try:
                    text.modifyText(text="日本語😀")
                    text.setSelection(text.pointDocumentBegin(), text.pointDocumentEnd())
                    text.modifyText(text=None)
                    record = text.doc.undo_list[-1]
                    self.assertIsNone(record.new_text)
                    self.assertTrue(text.undo())
                    self.assertEqual(text.doc.lines[0].s, "日本語😀")
                    self.assertTrue(text.redo())
                    self.assertEqual(text.doc.lines[0].s, "")
                    text.setSelection(text.pointDocumentBegin(), text.pointDocumentBegin(), block_mode=True)
                    with self.assertRaises(AttributeError) as error:
                        text.modifyText(text=None)
                    self.assertEqual(error.exception.name, "splitlines")
                    self.assertIsNone(error.exception.obj)
                    self.assertEqual(edit.getAutoComplete(), -7)
                    candidate = edit.list_window
                    with self.assertRaisesRegex(TypeError, "^cannot unpack non-iterable NoneType object$"):
                        edit.popupList()
                    self.assertIs(edit.list_window, candidate)
                    edit.popupListPrepare(complete=False)
                    prepared = edit.list_window_prepared_info
                    with patch.object(edit, "alternateText", side_effect=RuntimeError("alternate")), self.assertRaises(RuntimeError):
                        edit.popupList()
                    self.assertIs(edit.list_window_prepared_info, prepared)
                    edit.popupList()
                    self.assertIsNone(edit.list_window_prepared_info)
                    candidate = edit.list_window
                    assert candidate is not None
                    self.assertEqual(candidate.numItems(), 2)
                finally:
                    edit.destroy()
                    text.destroy()

            def test_native_edit_candidate_reuse_updates_completion_base(self):
                user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
                user32.IsWindow.argtypes = (wintypes.HWND,)
                for first_length, second_length in ((40, 50), (50, 40)):
                    for stage in ("success", "failure_before", "failure_after"):
                        with self.subTest(first=first_length, second=second_length, stage=stage):
                            first = "C:\\" + "A" * first_length + "\\a"
                            second = "C:\\" + "B" * second_length + "\\a"
                            owned = []
                            edit = ckit.EditWidget(self.window, 0, 0, 20, 1, first,
                                candidate_handler=lambda info: (["alpha", "alpine"], info.text.rfind("\\") + 1))
                            try:
                                initial = edit.list_window
                                assert initial is not None
                                initial_hwnd = initial.getHWND()
                                owned.append((initial, initial_hwnd))
                                edit.popupListPrepare(complete=False)
                                edit.popupList()
                                self.pump(lambda initial_hwnd=initial_hwnd: not user32.IsWindow(initial_hwnd))
                                current = edit.list_window
                                assert current is not None
                                hwnd = current.getHWND()
                                owned.append((current, hwnd))
                                old_base = edit.list_window_base_len
                                old_pos = edit.list_window_possize_info
                                edit.setText(second)
                                edit.setSelection([len(second), len(second)])
                                edit.makeVisible(len(second))
                                edit.popupListPrepare(complete=False)
                                prepared = edit.list_window_prepared_info
                                base = second.rfind("\\") + 1
                                if stage != "success":
                                    failure = RuntimeError("reused candidate update failed")
                                    set_items = current.setItems
                                    observed = []
                                    def failed(*args, edit=edit, observed=observed, stage=stage,
                                               failure=failure, set_items=set_items):
                                        observed.append(edit.list_window_base_len)
                                        if stage == "failure_after":
                                            set_items(*args)
                                        raise failure
                                    with patch.object(current, "setItems", side_effect=failed), \
                                         self.assertRaises(RuntimeError) as caught:
                                        edit.popupList()
                                    self.assertIs(caught.exception, failure)
                                    self.assertEqual(observed, [base])
                                    self.assertEqual(edit.list_window_base_len, old_base)
                                    self.assertIs(edit.list_window_prepared_info, prepared)
                                    self.assertIs(edit.list_window_possize_info, old_pos)
                                    self.assertIs(edit.list_window, current)
                                    self.assertTrue(user32.IsWindow(hwnd))
                                edit.popupList()
                                self.assertIs(edit.list_window, current)
                                self.assertIs(edit.list_window_possize_info, old_pos)
                                self.assertIsNone(edit.list_window_prepared_info)
                                self.assertTrue(user32.PostMessageW(hwnd, 0x0100, ckit.VK_DOWN, 0))
                                self.pump(lambda edit=edit, second=second: edit.getText() != second)
                                expected = second[:base] + "alpha"
                                self.assertEqual(edit.getText(), expected)
                                self.assertEqual(edit.list_window_base_len, base)
                                self.assertEqual(edit.getSelection(), [len(second), len(expected)])
                                edit.undo()
                                self.assertEqual(edit.getText(), second)
                                self.assertEqual(edit.getSelection(), [len(second), len(second)])
                                edit.redo()
                                self.assertEqual(edit.getText(), expected)
                                self.assertEqual(edit.getSelection(), [len(expected), len(expected)])
                            finally:
                                edit.destroy()
                                for child, handle in owned:
                                    if user32.IsWindow(handle):
                                        child.destroy()

            def test_native_edit_candidate_replacement_failure_restores_owner(self):
                user32.IsWindow.argtypes = (wintypes.HWND,)
                for stage in ("create", "schedule_before", "schedule_after", "items", "items_after_callback"):
                    for enabled in (False, True):
                        with self.subTest(stage=stage, enabled=enabled):
                            offers = [["alpha", "alpine"], 0]
                            owned = []
                            edit = ckit.EditWidget(self.window, 0, 0, 20, 1, "a",
                                candidate_handler=lambda info, offers=offers: (offers[0], offers[1]))
                            try:
                                initial = edit.list_window
                                assert initial is not None
                                initial_hwnd = initial.getHWND()
                                owned.append((initial, initial_hwnd))
                                edit.popupListPrepare(complete=False)
                                edit.popupList()
                                self.pump(lambda initial_hwnd=initial_hwnd: not user32.IsWindow(initial_hwnd))
                                old = edit.list_window
                                assert old is not None
                                old_hwnd = old.getHWND()
                                owned.append((old, old_hwnd))
                                old.enable(enabled)
                                old_base = edit.list_window_base_len
                                old_pos = edit.list_window_possize_info
                                offers[:] = [["beta", "bravo", "bright"], 1]
                                edit.popupListPrepare(complete=False)
                                prepared = edit.list_window_prepared_info
                                failure = RuntimeError("replacement failed")
                                create = edit.createCandidateWindow
                                schedule = self.window.delayedCall
                                dispatched = []
                                def created(stage=stage, failure=failure, create=create, owned=owned, dispatched=dispatched):
                                    if stage == "create":
                                        raise failure
                                    child = create()
                                    owned.append((child, child.getHWND()))
                                    set_items = child.setItems
                                    def items(*args):
                                        set_items(*args)
                                        if stage == "items_after_callback":
                                            self.pump(lambda: bool(dispatched))
                                        if stage in ("items", "items_after_callback"):
                                            raise failure
                                    child.setItems = items
                                    return child
                                def scheduled(callback, delay, stage=stage, failure=failure,
                                              schedule=schedule, dispatched=dispatched):
                                    if stage == "schedule_before":
                                        raise failure
                                    def delivered():
                                        dispatched.append(True)
                                        callback()
                                    schedule(delivered, delay)
                                    if stage == "schedule_after":
                                        raise failure
                                with patch.object(edit, "createCandidateWindow", side_effect=created), \
                                     patch.object(self.window, "delayedCall", side_effect=scheduled), \
                                     self.assertRaises(RuntimeError) as caught:
                                    edit.popupList()
                                self.assertIs(caught.exception, failure)
                                barrier = []
                                schedule(lambda barrier=barrier: barrier.append(True), 80)
                                self.pump(lambda barrier=barrier: bool(barrier))
                                self.assertTrue(user32.IsWindow(old_hwnd))
                                self.assertIs(edit.list_window, old)
                                self.assertEqual(old.isEnabled(), enabled)
                                self.assertEqual(old.numItems(), 2)
                                self.assertEqual(edit.list_window_base_len, old_base)
                                self.assertIs(edit.list_window_possize_info, old_pos)
                                self.assertIs(edit.list_window_prepared_info, prepared)
                                self.assertEqual(edit.getText(), "a")
                                for _child, hwnd in owned[2:]:
                                    self.assertFalse(user32.IsWindow(hwnd))
                                edit.popupList()
                                current = edit.list_window
                                assert current is not None
                                owned.append((current, current.getHWND()))
                                self.assertEqual(current.numItems(), 3)
                                self.assertIsNone(edit.list_window_prepared_info)
                                self.pump(lambda old_hwnd=old_hwnd: not user32.IsWindow(old_hwnd))
                            finally:
                                edit.destroy()
                                for child, hwnd in owned:
                                    if user32.IsWindow(hwnd):
                                        child.destroy()

            def test_native_filter_lines_whole_rows_and_undo_redo(self):
                ckit.TextWidget.updateColor()
                cases = (
                    ("nonempty", "keep\ndrop\ntail", (0, 0), (2, 4), bool,
                     ["keep", "drop", "tail"], "keep\r\ndrop\r\ntail"),
                    ("middle", "keep\ndrop\ntail", (0, 0), (2, 4), lambda text: text != "drop",
                     ["keep", "drop", "tail"], "keep\r\ntail"),
                    ("all", "a\nb\nc", (0, 0), (2, 1), lambda text: False,
                     ["a", "b", "c"], ""),
                    ("trailing_newline", "keep\ndrop\ntail\n", (0, 0), (3, 0), lambda text: text != "drop",
                     ["keep", "drop", "tail"], "keep\r\ntail\r\n"),
                    ("last_row", "keep\ntail", (1, 2), (1, 4), lambda text: False,
                     ["tail"], "keep\r\n"),
                    ("unicode", "日本語😀\n捨てる\n終端", (0, 0), (2, 2), lambda text: text != "捨てる",
                     ["日本語😀", "捨てる", "終端"], "日本語😀\r\n終端"),
                )
                for name, text, start, end, keep, expected_calls, expected in cases:
                    for reverse in (False, True):
                        with self.subTest(case=name, reverse=reverse):
                            edit = ckit.TextWidget(self.window, 0, 0, 30, 5)
                            try:
                                edit.modifyText(text=text)
                                original = edit.getText(edit.pointDocumentBegin(), edit.pointDocumentEnd())
                                left, right = edit.point(*start), edit.point(*end)
                                edit.setSelection(right, left) if reverse else edit.setSelection(left, right)
                                seen = []
                                def predicate(text, info, seen=seen, keep=keep):
                                    seen.append(text)
                                    return keep(text)
                                edit.filterLines(predicate)
                                self.assertEqual(seen, expected_calls)
                                self.assertEqual(edit.getText(edit.pointDocumentBegin(), edit.pointDocumentEnd()), expected)
                                selection = edit.selection.left(), edit.selection.right()
                                self.assertEqual(selection[0], left.lineBegin())
                                self.assertLessEqual(selection[1], edit.pointDocumentEnd())
                                self.assertTrue(edit.undo())
                                self.assertEqual(edit.getText(edit.pointDocumentBegin(), edit.pointDocumentEnd()), original)
                                self.assertTrue(edit.redo())
                                self.assertEqual(edit.getText(edit.pointDocumentBegin(), edit.pointDocumentEnd()), expected)
                                self.assertEqual((edit.selection.left(), edit.selection.right()), selection)
                            finally:
                                edit.destroy()

            def test_native_text_candidate_delayed_owner_cleanup(self):
                import gc
                import weakref

                from ckit import ckit_textwidget

                user32.IsWindow.argtypes = (wintypes.HWND,)
                class Parent(ckit.TextWindow):
                    def __init__(self):
                        super().__init__(x=0, y=0, width=30, height=6, show=False)
                        self.command = ckit.CommandMap(self)
                ckit.TextWidget.updateColor()
                for scenario in ("normal", "widget_destroy", "parent_destroy", "registration_failure"):
                    with self.subTest(scenario=scenario):
                        parent = Parent()
                        text = ckit.TextWidget(parent, 0, 0, 30, 5)
                        old = ckit_textwidget.CandidateWindow(0, 0, 10, 1, 30, 5, parent)
                        hwnd = old.getHWND()
                        plane = vars(old)["_TextWindow__text"]
                        old_ref = weakref.ref(old)
                        scheduled = []
                        schedule = parent.delayedCall
                        text.candidate_window = old
                        parent_destroyed = text_destroyed = False
                        def record(callback, timeout, schedule=schedule, scheduled=scheduled):
                            self.assertEqual(timeout, 50)
                            scheduled.append(weakref.ref(callback))
                            schedule(callback, timeout)
                        try:
                            if scenario == "registration_failure":
                                failure = ValueError("registration failed before enqueue")
                                with patch.object(parent, "delayedCall", side_effect=failure), \
                                     self.assertRaises(ValueError) as caught:
                                    text.closeList(delay=True)
                                self.assertIs(caught.exception, failure)
                                self.assertIs(text.candidate_window, old)
                                self.assertTrue(user32.IsWindow(hwnd))
                                text.closeList()
                                self.assertIsNone(text.candidate_window)
                            else:
                                with patch.object(parent, "delayedCall", record):
                                    text.closeList(delay=True)
                                self.assertIsNone(text.candidate_window)
                                self.assertTrue(user32.IsWindow(hwnd))
                                self.assertIsNotNone(scheduled[0]())
                                del old
                                if scenario in ("widget_destroy", "parent_destroy"):
                                    text.destroy()
                                    text_destroyed = True
                                if scenario == "parent_destroy":
                                    parent.destroy()
                                    parent_destroyed = True
                                else:
                                    deadline = time.monotonic() + 2
                                    parent.messageLoop(lambda hwnd=hwnd, deadline=deadline:
                                                       bool(user32.IsWindow(hwnd)) and time.monotonic() < deadline)
                                self.assertIsNone(scheduled[0]())
                                gc.collect()
                                self.assertIsNone(old_ref())
                            self.assertFalse(user32.IsWindow(hwnd))
                            with self.assertRaisesRegex(ValueError, "^already destroyed\\.$"):
                                plane.getPosition()
                        finally:
                            if not text_destroyed:
                                text.destroy()
                            if user32.IsWindow(hwnd):
                                remaining = old_ref()
                                assert remaining is not None
                                remaining.destroy()
                            if not parent_destroyed:
                                parent.destroy()

            def test_native_candidate_constructor_failure_releases_resources(self):
                from ckit import ckit_textwidget, ckit_textwindow, ckit_widget, ckitcore

                user32.IsWindow.argtypes = (wintypes.HWND,)
                initialize = ckit_textwindow.TextWindow.__init__
                plane_type = ckitcore.TextPlane
                parent_hwnd = self.window.getHWND()
                parent_enabled = self.window.isEnabled()
                for cls in (ckit_widget.CandidateWindow, ckit_textwidget.CandidateWindow):
                    for stage in ("setItems", "paint"):
                        with self.subTest(candidate=cls.__module__, stage=stage):
                            acquired = []
                            destroyed_planes = []
                            class Plane:
                                def __init__(self, *args):
                                    self.native = plane_type(*args)
                                def __getattr__(self, name):
                                    return getattr(self.native, name)
                                def destroy(self, destroyed_planes=destroyed_planes):
                                    self.native.destroy()
                                    destroyed_planes.append(self.native)
                            def capture(child, acquired=acquired, **kwargs):
                                initialize(child, **kwargs)
                                acquired.append((child, child.getHWND()))
                            failure = RuntimeError("candidate initial layout failed")
                            try:
                                with patch.object(ckitcore, "TextPlane", Plane), \
                                     patch.object(ckit_textwindow.TextWindow, "__init__", capture), \
                                     patch.object(cls, stage, side_effect=failure), \
                                     self.assertRaises(RuntimeError) as caught:
                                    cls(0, 0, 10, 1, 80, 16, self.window)
                                self.assertIs(caught.exception, failure)
                                self.assertEqual(len(acquired), 1)
                                self.assertFalse(user32.IsWindow(acquired[0][1]))
                                self.assertEqual(len(destroyed_planes), 1)
                                self.assertTrue(user32.IsWindow(parent_hwnd))
                                self.assertEqual(self.window.isEnabled(), parent_enabled)
                                candidate = cls(0, 0, 10, 1, 80, 16, self.window)
                                hwnd = candidate.getHWND()
                                try:
                                    candidate.setItems(0, 0, 20, ["alpha", "beta"], 1)
                                    self.assertEqual(candidate.getSelection(), 1)
                                    self.assertEqual(candidate.numItems(), 2)
                                    self.assertTrue(user32.IsWindow(hwnd))
                                finally:
                                    candidate.destroy()
                                self.assertFalse(user32.IsWindow(hwnd))
                            finally:
                                for child, hwnd in acquired:
                                    if user32.IsWindow(hwnd):
                                        ckit_textwindow.TextWindow.destroy(child)

            def test_native_text_candidate_stale_queued_keys(self):
                user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
                user32.IsWindow.argtypes = (wintypes.HWND,)
                ckit.TextWidget.updateColor()
                for key in (ckit.VK_RETURN, ckit.VK_TAB):
                    for state in ("replaced", "out_of_range", "empty", "auto_fix"):
                        with self.subTest(key=key, state=state):
                            text = ckit.TextWidget(self.window, 0, 0, 30, 5)
                            delivered = []
                            errors = io.StringIO()
                            old_windows = []
                            try:
                                text.modifyText(text="pre")
                                def complete(*args, state=state, text=text, old_windows=old_windows):
                                    items = ["old"] if state == "out_of_range" else ["old0", "old1"]
                                    if old_windows:
                                        items = [] if state == "empty" else ["fixed"] if state == "auto_fix" else ["new0", "new1"]
                                    return SimpleNamespace(items=items, selection=int(items == ["new0", "new1"]),
                                        left=text.pointDocumentBegin(), right=text.pointDocumentEnd())
                                with patch.object(text.doc.mode.completion, "getCandidateList", side_effect=complete):
                                    text.popupList(auto_fix=False)
                                    old = text.candidate_window
                                    assert old is not None
                                    old_windows.append(old)
                                    hwnd = old.getHWND()
                                    original_hook = old.keydown_hook
                                    assert original_hook is not None
                                    def observe(vk, mod, original_hook=original_hook, delivered=delivered):
                                        try:
                                            return original_hook(vk, mod)
                                        finally:
                                            delivered.append((vk, mod))
                                    old.keydown_hook = observe
                                    self.assertTrue(user32.PostMessageW(hwnd, 0x0100, key, 0))
                                    text.popupList(auto_fix=state == "auto_fix")
                                    current = text.candidate_window
                                    expected = "fixed" if state == "auto_fix" else "pre"
                                    undo = list(text.doc.undo_list)
                                    with redirect_stderr(errors):
                                        self.pump(lambda delivered=delivered: bool(delivered))
                                    self.assertEqual(delivered, [(key, 0)])
                                    self.assertEqual(errors.getvalue(), "")
                                    self.assertEqual(text.doc.lines[0].s, expected)
                                    self.assertEqual(text.doc.undo_list, undo)
                                    self.assertIs(text.candidate_window, current)
                                    if current is not None:
                                        self.assertTrue(user32.IsWindow(current.getHWND()))
                                        self.assertEqual(current.getSelection(), 1)
                                    self.pump(lambda hwnd=hwnd: not user32.IsWindow(hwnd))
                                    if current is not None:
                                        current_hwnd = current.getHWND()
                                        self.assertTrue(user32.IsWindow(current_hwnd))
                                        self.assertTrue(user32.PostMessageW(current_hwnd, 0x0100, key, 0))
                                        with redirect_stderr(errors):
                                            self.pump(lambda text=text, expected=expected: text.doc.lines[0].s != expected)
                                        self.assertEqual(errors.getvalue(), "")
                                        self.assertEqual(text.doc.lines[0].s, "new1" if key == ckit.VK_RETURN else "new")
                                        if key == ckit.VK_RETURN:
                                            self.assertIsNone(text.candidate_window)
                                        else:
                                            self.assertIsNotNone(text.candidate_window)
                                            self.assertIsNot(text.candidate_window, current)
                                        self.pump(lambda current_hwnd=current_hwnd: not user32.IsWindow(current_hwnd))
                            finally:
                                text.destroy()

            def test_native_text_measurement_offsets(self):
                window = self.window
                for method in (window.getStringWidth, window.getStringColumns):
                    for tab_width in (0, -1):
                        with self.assertRaisesRegex(ValueError, "tab_width"):
                            method("\t", tab_width)
                for text in ("", "abc", "\t", "a\tb", "全\t😀\t末", "\t\t"):
                    for tab_width in (1, 4, 7):
                        for offset in (*range(-9, 10), -2147483648, 2147483647):
                            with self.subTest(text=text, tab=tab_width, offset=offset):
                                expanded = ckit.expandTab(window, text, tab_width, offset)
                                expected = window.getStringWidth(expanded)
                                columns = window.getStringColumns(text, tab_width, offset)
                                self.assertEqual(window.getStringWidth(text, tab_width, offset), expected)
                                self.assertEqual(columns[0], 0)
                                self.assertEqual(columns[-1], expected)
                                self.assertEqual(len(columns), len(text.encode("utf-16-le")) // 2 + 1)
                                unit = 0
                                for index, char in enumerate(text):
                                    self.assertEqual(columns[unit], window.getStringWidth(text[:index], tab_width, offset))
                                    unit += 2 if ord(char) > 0xFFFF else 1
                                for index in range(len(text) + 1):
                                    left = window.getStringWidth(text[:index], tab_width, offset)
                                    right = window.getStringWidth(text[index:], tab_width, (offset + left) % tab_width)
                                    self.assertEqual(left + right, expected)

            def test_native_shared_textwidget_positions_and_undo(self):
                ckit.TextWidget.updateColor()
                host = ckit.TextWindow(width=40, height=18, show=False, parent_window=self.window)
                self.addCleanup(host.destroy)
                host.command = ckit.CommandMap(host)
                views = [ckit.TextWidget(host, 0, row * 6, 40, 5) for row in range(3)]
                for view in views:
                    self.addCleanup(view.destroy)
                first, second, third = views
                original = ["A😀\t全abcdef", "後続😀abcdef", "last"]
                first.modifyText(text="\n".join(original))
                second.setDocument(first.doc)
                third.setDocument(first.doc)
                second.setSelection(second.point(0, 7), second.point(1, 4))
                third.setCursor(third.point(1, 4))
                first.modifyText(first.point(0, 1), first.point(0, 4), "Z\n語")
                changed = ["AZ", "語abcdef", "後続😀abcdef", "last"]
                self.assertEqual([line.s for line in first.doc.lines], changed)
                self.assertEqual((second.selection.anchor(), second.selection.cursor()),
                                 (second.point(1, 4), second.point(2, 4)))
                self.assertEqual(third.selection.cursor(), third.point(2, 4))
                self.assertEqual(first.selection.cursor(), first.point(1, 1))
                for view in views:
                    cursor = view.selection.cursor()
                    prefix = view.doc.lines[cursor.line].s[:cursor.index]
                    expected_x = view.x + view.lineNoWidth() + host.getStringWidth(prefix, view.doc.mode.tab_width)
                    self.assertEqual(view.getCursorPos(),
                                     (expected_x - view.visible_first_column,
                                      view.y + cursor.line - view.visible_first_line))
                    view.paint()
                host.flushPaint()
                self.assertTrue(first.undo())
                self.assertEqual([line.s for line in first.doc.lines], original)
                self.assertEqual((second.selection.anchor(), second.selection.cursor()),
                                 (second.point(0, 7), second.point(1, 4)))
                self.assertEqual(third.selection.cursor(), third.point(1, 4))
                # The undo history is shared, and any attached view may replay it.
                self.assertTrue(third.redo())
                self.assertEqual([line.s for line in first.doc.lines], changed)
                self.assertEqual((second.selection.anchor(), second.selection.cursor()),
                                 (second.point(1, 4), second.point(2, 4)))
                self.assertEqual(third.selection.cursor(), third.point(1, 1))
                first.setCursor(first.pointDocumentBegin())
                first.atomicUndoBegin()
                first.modifyText(text="Q\n")
                first.modifyText(text="R")
                first.atomicUndoEnd()
                self.assertEqual((second.selection.anchor(), second.selection.cursor()),
                                 (second.point(2, 4), second.point(3, 4)))
                self.assertTrue(first.undo())
                self.assertEqual([line.s for line in first.doc.lines], changed)
                self.assertEqual((second.selection.anchor(), second.selection.cursor()),
                                 (second.point(1, 4), second.point(2, 4)))
                self.assertTrue(first.redo())
                self.assertEqual((second.selection.anchor(), second.selection.cursor()),
                                 (second.point(2, 4), second.point(3, 4)))
                second.setCursor(second.point(0, 1))
                first.modifyText(first.point(0, 0), first.point(1, 1), "全長")
                self.assertIs(second.selection.cursor().edit, second)
                self.assertEqual(second.selection.cursor(), second.point(0, 0))
                self.assertEqual(second.selection.cursor().down(), second.point(1, 0))

            def test_native_textwidget_unicode_positions_search_and_edit(self):
                ckit.TextWidget.updateColor()
                edit = ckit.TextWidget(self.window, 0, 0, 40, 5)
                try:
                    text = "A😀\t全xßxﬃx"
                    edit.modifyText(text=text)
                    for index in range(len(text) + 1):
                        column = edit.getColumnFromIndex(0, index)
                        self.assertEqual(column, self.window.getStringWidth(text[:index], edit.doc.mode.tab_width))
                        self.assertEqual(edit.getIndexFromColumn(0, column), index)
                        x = edit.x + edit.lineNoWidth() + column - edit.visible_first_column
                        pixel = self.window.charToClient(x, edit.y)
                        origin = self.window.charToClient(0, 0)
                        cw, ch = self.window.getCharSize()
                        self.assertEqual(((pixel[0] - origin[0]) // cw, (pixel[1] - origin[1]) // ch), (x, edit.y))
                        edit.onLeftButtonDown(x, edit.y, 0.0, 0.0, 0)
                        edit.onLeftButtonUp(x, edit.y, 0.0, 0.0, 0)
                        self.assertEqual(edit.selection.cursor(), edit.point(0, index))
                    for index in (1, 2, 3):
                        end_column = edit.getColumnFromIndex(0, len(text))
                        self.assertEqual(edit.getIndexFromColumn(0, end_column + index, block_mode=True), len(text) + index)
                        self.assertEqual(edit.getColumnFromIndex(0, len(text) + index), end_column + index)
                    # A click within a surrogate pair or wide glyph never yields a UTF-16 index.
                    for index in (1, 3):
                        left = edit.getColumnFromIndex(0, index)
                        right = edit.getColumnFromIndex(0, index + 1)
                        for fraction, expected in ((0.24, index), (0.25, index + 1)):
                            middle = (left + right) / 2
                            column = int(middle)
                            self.assertEqual(edit.getIndexFromColumn(0, column, middle - column + fraction), expected)
                    search = ckit.Search("x", False, False, False)
                    for direction, start, expected in ((1, 0, 4), (1, 5, 6), (1, 7, 8), (-1, 9, 8), (-1, 8, 6), (-1, 6, 4)):
                        found = edit.search(search, edit.point(0, start), direction=direction, message=False)
                        self.assertEqual(found, edit.point(0, expected))
                        self.assertEqual(edit.getText(edit.selection.left(), edit.selection.right()), "x")
                    for query, start, end in (("s", 5, 6), ("ssx", 5, 7), ("fi", 7, 8), ("ix", 7, 9)):
                        found = edit.search(ckit.Search(query, False, False, False), edit.point(0, start), message=False)
                        self.assertEqual(found, edit.point(0, start))
                        self.assertEqual(edit.selection.left(), edit.point(0, start))
                        self.assertEqual(edit.selection.right(), edit.point(0, end))
                    edit.onLeftButtonDown(edit.lineNoWidth() + edit.getColumnFromIndex(0, 1), 0, 0.0, 0.0, 0)
                    edit.onMouseMove(edit.lineNoWidth() + edit.getColumnFromIndex(0, 4), 0, 0.0, 0.0, 0)
                    edit.onLeftButtonUp(edit.lineNoWidth() + edit.getColumnFromIndex(0, 4), 0, 0.0, 0.0, 0)
                    self.assertEqual(edit.getText(edit.selection.left(), edit.selection.right()), "😀\t全")
                    edit.modifyText(text="Z")
                    self.assertEqual(edit.doc.lines[0].s, "AZxßxﬃx")
                    self.assertTrue(edit.undo())
                    self.assertEqual(edit.doc.lines[0].s, text)
                    self.assertTrue(edit.redo())
                    self.assertEqual(edit.doc.lines[0].s, "AZxßxﬃx")
                    edit.setSelection(edit.pointDocumentBegin(), edit.pointDocumentEnd(), block_mode=False)
                    edit.modifyText(text="A😀\t全x\nB😀\t全y")
                    edit.setSelection(edit.point(0, 1), edit.point(1, 2), block_mode=True)
                    self.assertEqual(edit.getText(edit.selection.left(), edit.selection.right(), True), "😀\r\n😀")
                    edit.modifyText(text="")
                    self.assertEqual([line.s for line in edit.doc.lines], ["A\t全x", "B\t全y"])
                    self.assertTrue(edit.undo())
                    self.assertEqual([line.s for line in edit.doc.lines], ["A😀\t全x", "B😀\t全y"])
                    self.assertTrue(edit.redo())
                    self.assertEqual([line.s for line in edit.doc.lines], ["A\t全x", "B\t全y"])
                finally:
                    document = edit.doc
                    edit.destroy()
                    self.assertNotIn(edit.onDocumentTextModified, document.text_modified_handler_list)

            def test_native_atomic_undo_end(self):
                ckit.TextWidget.updateColor()
                edit = ckit.TextWidget(self.window, 0, 0, 30, 5)
                try:
                    edit.modifyText(text="base")
                    edit.atomicUndoBegin()
                    info = edit.doc.atomic_undo
                    edit.modifyText(text="one")
                    edit.modifyText(text="two")
                    edit.atomicUndoEnd()
                    self.assertIsNone(edit.doc.atomic_undo)
                    self.assertIs(edit.doc.undo_list[-1], info)
                    self.assertTrue(edit.undo())
                    self.assertEqual(edit.doc.lines[0].s, "base")
                    self.assertTrue(edit.redo())
                    self.assertEqual(edit.doc.lines[0].s, "baseonetwo")
                    with self.assertRaises(AttributeError) as raised:
                        edit.atomicUndoEnd()
                    self.assertEqual(raised.exception.name, "new_anchor")
                    self.assertIsNone(raised.exception.obj)
                finally:
                    edit.destroy()

            def modal_desktop_state(self):
                user32.GetForegroundWindow.restype = wintypes.HWND
                user32.GetActiveWindow.restype = wintypes.HWND
                user32.GetFocus.restype = wintypes.HWND
                user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
                user32.GetWindow.restype = wintypes.HWND
                user32.IsWindow.argtypes = (wintypes.HWND,)
                if interactive_foreground:
                    previous = user32.GetForegroundWindow()
                    self.addCleanup(lambda: user32.SetForegroundWindow(previous))

            def assert_modal_parent(self, child, parent, visible):
                self.assertEqual(user32.GetWindow(child.getHWND(), 4), parent.getHWND())
                self.assertFalse(parent.isEnabled())
                if interactive_foreground:
                    self.assertEqual(parent.isVisible(), visible)
                    self.assertTrue(child.isVisible())
                    self.assertEqual(user32.GetActiveWindow(), child.getHWND())
                    self.assertEqual(user32.GetFocus(), child.getHWND())

            def test_native_editor_modal_parent_states(self):
                self.modal_desktop_state()
                for visible in (True, False):
                    for enabled in (True, False):
                        for outcome in ("save", "cancel", "loop_error", "shown_error", "saved_error", "create_error"):
                            with self.subTest(visible=visible, enabled=enabled, outcome=outcome):
                                self.apply({"tool": {"target": {"link": "tool.exe"}}})
                                before = (data / "commands.json").read_bytes()
                                self.window.enable(enabled)
                                self.window.show(visible, False)
                                original = clnch_cmdeditor.CommandEditor
                                handles = []
                                def create(*args, original=original, handles=handles, **kwargs):
                                    editor = original(*args, **kwargs)
                                    handles.append(editor.getHWND())
                                    return editor
                                def operate(editor, visible=visible, outcome=outcome):
                                    self.assert_modal_parent(editor, self.window, visible)
                                    editor.edit_by_id["name"].setText("saved")
                                    self.key(ckit.VK_RETURN if outcome in ("save", "saved_error") else ckit.VK_ESCAPE, window=editor)
                                def failed(*args, outcome=outcome, **kwargs):
                                    raise RuntimeError(outcome)
                                with ExitStack() as stack:
                                    activate = stack.enter_context(patch.object(self.window, "activate", wraps=self.window.activate))
                                    reload_commands = stack.enter_context(patch.object(self.ui, "reload_commands",
                                        side_effect=failed if outcome == "saved_error" else self.ui.reload_commands))
                                    stack.enter_context(patch.object(clnch_cmdeditor, "CommandEditor",
                                        side_effect=failed if outcome == "create_error" else create))
                                    if outcome == "loop_error":
                                        stack.enter_context(patch.object(ckit.TextWindow, "messageLoop", side_effect=failed))
                                    if outcome.endswith("error"):
                                        with self.assertRaisesRegex(RuntimeError, outcome):
                                            self.run_editor(operate, target="tool", shown=failed if outcome == "shown_error" else None)
                                    else:
                                        result = self.run_editor(operate, target="tool")
                                        self.assertEqual(result, "saved" if outcome == "save" else None)
                                    self.assertEqual(reload_commands.call_count, int(outcome in ("save", "saved_error")))
                                    self.assertEqual(activate.call_count, int(enabled and outcome != "create_error"))
                                self.assertEqual(self.window.isEnabled(), enabled)
                                if interactive_foreground:
                                    self.assertEqual(self.window.isVisible(), visible)
                                    if visible and enabled and outcome != "create_error":
                                        self.assertEqual(user32.GetActiveWindow(), self.window.getHWND())
                                        self.assertEqual(user32.GetFocus(), self.window.getHWND())
                                self.assertTrue(all(not user32.IsWindow(hwnd) for hwnd in handles))
                                if outcome not in ("save", "saved_error"):
                                    self.assertEqual((data / "commands.json").read_bytes(), before)
                self.window.enable(True)
                self.window.show(True, False)
                # Exercise the actual Ctrl+E/new key dispatch and main-window drop handler.
                for entry in (lambda: self.input_action("tool", lambda: self.key(ord("E"), 2)),
                              lambda: self.input_action("new", lambda: self.key(ckit.VK_RETURN)),
                              lambda: self.window.command_drop_handler([str(probe)])):
                    self.run_editor(lambda editor: (self.assert_modal_parent(editor, self.window, True),
                        self.key(ckit.VK_ESCAPE, window=editor)), entry=entry)

            def test_native_list_modal_parent_return(self):
                self.modal_desktop_state()
                for operation in ("save", "cancel", "new", "drop", "error"):
                    with self.subTest(operation=operation):
                        self.apply({"tool": {"target": {"link": "tool.exe"}}})
                        self.window.show(True, False)
                        listings, failures = [], []
                        original = clnch_cmdlist.CommandListWindow
                        def create(*args, original=original, listings=listings, operation=operation, failures=failures, **kwargs):
                            previous = listings[-1] if listings else None
                            if previous:
                                self.assertTrue(user32.IsWindow(previous.getHWND()))
                                if interactive_foreground:
                                    self.assertTrue(previous.isVisible())
                            listing = original(*args, **kwargs)
                            stage = len(listings)
                            listings.append(listing)
                            show = listing.show
                            def shown(visible):
                                if previous:
                                    self.assertTrue(user32.IsWindow(previous.getHWND()))
                                    if interactive_foreground:
                                        self.assertTrue(previous.isVisible())
                                show(visible)
                            listing.show = shown
                            destroy = listing.destroy
                            def retired():
                                try:
                                    if stage == 0 and operation != "error":
                                        self.assertEqual(len(listings), 2)
                                        if interactive_foreground:
                                            self.assertTrue(listings[1].isVisible())
                                finally:
                                    destroy()
                            listing.destroy = retired
                            def drive():
                                listing.killTimer(drive)
                                try:
                                    self.assert_modal_parent(listing, self.window, True)
                                    if stage:
                                        self.assertEqual(listing.items[listing.select][1], "renamed" if operation == "save" else "tool")
                                        self.key(ckit.VK_ESCAPE, window=listing)
                                    else:
                                        listing.select = next(i for i, item in enumerate(listing.items) if item[1] == "tool")
                                        if operation == "drop":
                                            kwargs["dropfiles_handler"](0, 0, [str(probe)])
                                        else:
                                            self.key(ckit.VK_INSERT if operation == "new" else ckit.VK_RETURN, window=listing)
                                except BaseException as error:  # noqa: BLE001  # Surface timer assertions and exit the native loop.
                                    failures.append(error)
                                    listing.cancel()
                            listing.setTimer(drive, 30)
                            return listing
                        def edit(name, parent_window, listings=listings, operation=operation, **options):
                            self.assertIs(parent_window, listings[-1])
                            def operate(editor):
                                self.assert_modal_parent(editor, parent_window, True)
                                base = parent_window.getWindowRect()
                                rect = editor.getWindowRect()
                                work = ckit.getWindowWorkArea(editor)
                                self.assertEqual(rect[0], max(work[0], min(base[2], work[2] - (rect[2] - rect[0]))))
                                self.assertEqual(rect[1], max(work[1], min(base[1], work[3] - (rect[3] - rect[1]))))
                                self.assertFalse(self.window.isEnabled())
                                if operation == "save":
                                    editor.edit_by_id["name"].setText("renamed")
                                self.key(ckit.VK_RETURN if operation == "save" else ckit.VK_ESCAPE, window=editor)
                            def failed():
                                raise RuntimeError("handoff")
                            result = self.run_editor(operate, target=name, parent=parent_window,
                                dropped_files=options.get("dropped_files"), shown=failed if operation == "error" else None)
                            self.assertTrue(parent_window.isEnabled())
                            if interactive_foreground:
                                self.assertTrue(parent_window.isVisible())
                                self.assertEqual(user32.GetActiveWindow(), parent_window.getHWND())
                                self.assertEqual(user32.GetFocus(), parent_window.getHWND())
                            return result
                        with patch.object(clnch_cmdlist, "CommandListWindow", side_effect=create), \
                             patch.object(self.window, "activate", wraps=self.window.activate) as activate:
                            if operation == "error":
                                with self.assertRaisesRegex(RuntimeError, "handoff"):
                                    clnch_cmdlist.open_list(self.window, on_edit=edit)
                            else:
                                clnch_cmdlist.open_list(self.window, on_edit=edit)
                            activate.assert_called_once_with()
                        self.assertEqual(failures, [])
                        self.assertTrue(self.window.isEnabled())
                        if interactive_foreground:
                            self.assertTrue(self.window.isVisible())
                            self.assertEqual(user32.GetActiveWindow(), self.window.getHWND())
                            self.assertEqual(user32.GetFocus(), self.window.getHWND())

            def test_native_list_edit_handoff(self):
                self.apply({"listed": {"target": {"link": str(probe)}}})
                original = clnch_cmdlist.CommandListWindow
                events = []
                def create(*args, **kwargs):
                    listing = original(*args, **kwargs)
                    def drive():
                        listing.killTimer(drive)
                        if events:
                            listing.onKeyDown(ckit.VK_ESCAPE, 0)
                        else:
                            listing.select = next(i for i, item in enumerate(listing.items) if item[1] == "listed")
                            listing.onKeyDown(ckit.VK_RETURN, 0)
                    listing.setTimer(drive, 30)
                    return listing
                def edit(name, parent_window):
                    events.append(name)
                    return self.run_editor(lambda editor: editor._on_keydown(ckit.VK_ESCAPE, 0),
                        target=name, parent=parent_window)
                with patch.object(clnch_cmdlist, "CommandListWindow", side_effect=create):
                    clnch_cmdlist.open_list(self.window, on_saved=self.ui.reload_commands, on_edit=edit)
                self.assertEqual(events, ["listed"])
                self.assertTrue(self.window.isEnabled())

            def test_native_list_duplicate_edit_save_cancel_and_selection(self):
                command = {modifier: clnch_cmdstore.normalize_action({"link": str(probe), "args": modifier})
                           for modifier in clnch_cmdstore.MODIFIERS}
                self.apply({"listed": command})
                original = clnch_cmdlist.CommandListWindow
                listings, failures = [], []
                def create(*args, **kwargs):
                    listing = original(*args, **kwargs)
                    stage = len(listings)
                    listings.append(listing)
                    shown = listing.show
                    listing.show_requests = []
                    def show(visible):
                        listing.show_requests.append(visible)
                        shown(visible)
                    listing.show = show
                    def drive():
                        listing.killTimer(drive)
                        try:
                            if stage == 0:
                                listing.select = next(i for i, item in enumerate(listing.items) if item[1] == "listed")
                                self.key(ckit.VK_INSERT, 2, window=listing)
                            elif stage in (1, 2):
                                expected = "listed_copy_1" if stage == 1 else "renamed_copy"
                                self.assertEqual(listing.items[listing.select][1], expected)
                                self.key(ckit.VK_RETURN, window=listing)
                            else:
                                self.assertEqual(listing.items[listing.select][1], "renamed_copy")
                                self.key(ckit.VK_ESCAPE, window=listing)
                        except BaseException as error:  # noqa: BLE001  # Surface timer assertions and leave the native modal loop.
                            failures.append(error)
                            listing.cancel()
                    listing.setTimer(drive, 30)
                    return listing
                edited = []
                def edit(name, parent_window):
                    self.assertFalse(self.window.isEnabled())
                    # Check the requested visibility separately from private-station activation.
                    self.assertEqual(listings[-1].show_requests, [True])
                    def operate(editor):
                        self.assertEqual(listings[-1].show_requests, [True])
                        self.assertFalse(parent_window.isEnabled())
                        if not edited:
                            self.assertEqual(name, "listed_copy_1")
                            editor.edit_by_id["name"].setText("renamed_copy")
                            self.key(ckit.VK_RETURN, window=editor)
                        else:
                            self.assertEqual(name, "renamed_copy")
                            editor.edit_by_id["link"].setText("cancelled.exe")
                            self.key(ckit.VK_ESCAPE, window=editor)
                    result = self.run_editor(operate, target=name, parent=parent_window)
                    edited.append(result)
                    return result
                with patch.object(clnch_cmdlist, "CommandListWindow", side_effect=create):
                    clnch_cmdlist.open_list(self.window, on_saved=self.ui.reload_commands, on_edit=edit)
                self.assertEqual(failures, [])
                self.assertEqual(edited, ["renamed_copy", None])
                self.assertEqual(len(listings), 4)
                self.assertEqual(json.loads((data / "commands.json").read_text(encoding="utf-8")),
                                 {"listed": command, "renamed_copy": command})
                self.assertTrue(self.window.isEnabled())

            def test_native_list_search_delete_failure_retry_drop_and_cancel(self):
                self.apply({"a": {}, "tool": {}, "z": {}})
                original = clnch_cmdlist.CommandListWindow
                listings, handles, failures, edits = [], [], [], []
                user32.IsWindow.argtypes = (wintypes.HWND,)
                def create(*args, **kwargs):
                    listing = original(*args, **kwargs)
                    stage = len(listings)
                    listings.append(listing)
                    handles.append(listing.getHWND())
                    def drive():
                        listing.killTimer(drive)
                        try:
                            self.assertFalse(self.window.isEnabled())
                            if stage == 0:
                                self.key(ckit.VK_F, 2, window=listing)
                                for ch in "TOOL":
                                    user32.SendMessageW(listing.getHWND(), 0x0102, ord(ch), 1)
                                self.assertEqual([item[1] for item in listing.items], ["tool"])
                                self.key(ckit.VK_ESCAPE, window=listing)
                            else:
                                expected = "tool" if stage == 1 else "z"
                                self.assertEqual(listing.items[listing.select][1], expected)
                            if stage < 2:
                                self.key(ckit.VK_DELETE, window=listing)
                            elif stage == 2:
                                kwargs["dropfiles_handler"](0, 0, [str(probe)])
                            else:
                                self.key(ckit.VK_ESCAPE, window=listing)
                        except BaseException as error:  # noqa: BLE001  # Surface timer assertions and close the native loop.
                            failures.append(error)
                            listing.cancel()
                    listing.setTimer(drive, 30)
                    return listing
                save = clnch_cmdlist.save_commands
                attempts = []
                def save_with_retry(*args):
                    attempts.append(True)
                    if len(attempts) == 1:
                        raise PermissionError("locked")
                    return save(*args)
                def edit(name, dropped_files, parent_window):
                    self.assertIsNone(name)
                    self.assertEqual(dropped_files, [str(probe)])
                    self.assertFalse(self.window.isEnabled())
                    self.assertTrue(user32.IsWindow(handles[-1]))
                    self.assertEqual(parent_window.getHWND(), handles[-1])
                    edits.append(name)
                    return self.run_editor(lambda editor: self.key(ckit.VK_ESCAPE, window=editor),
                                           dropped_files=dropped_files, parent=parent_window)
                with patch.object(clnch_cmdlist, "CommandListWindow", side_effect=create), \
                     patch.object(clnch_cmdlist, "_confirm_delete", return_value=True), \
                     patch.object(clnch_cmdlist, "save_commands", side_effect=save_with_retry), \
                     patch.object(clnch_cmdlist.clnch_msgbox, "popMessageBox") as popup, \
                     patch.object(self.ui, "reload_commands", wraps=self.ui.reload_commands) as reload_commands:
                    clnch_cmdlist.open_list(self.window, on_saved=reload_commands, on_edit=edit)
                self.assertEqual(failures, [])
                self.assertEqual(attempts, [True, True])
                self.assertEqual(edits, [None])
                popup.assert_called_once()
                reload_commands.assert_called_once_with()
                self.assertEqual(json.loads((data / "commands.json").read_text(encoding="utf-8")), {"a": {}, "z": {}})
                self.assertTrue(self.window.isEnabled())
                self.assertTrue(all(not user32.IsWindow(handle) for handle in handles))

            def test_native_list_failures_restore_parent_and_destroy_hwnd(self):
                original = clnch_cmdlist.CommandListWindow
                user32.IsWindow.argtypes = (wintypes.HWND,)
                for stage in ("position", "show", "loop", "result", "edit", "activate"):
                    with self.subTest(stage=stage):
                        handles = []
                        def fail(*args, **kwargs):
                            raise RuntimeError(stage)  # noqa: B023  # Used within this native test iteration.
                        def create(*args, **kwargs):
                            listing = original(*args, **kwargs)
                            handles.append(listing.getHWND())  # noqa: B023  # Used within this native test iteration.
                            if stage == "show":  # noqa: B023  # Used within this native test iteration.
                                listing.show = fail
                            listing.messageLoop = fail if stage == "loop" else lambda: None  # noqa: B023  # Used within this native test iteration.
                            if stage == "result":  # noqa: B023  # Used within this native test iteration.
                                listing.getResult = fail
                            elif stage != "edit":  # noqa: B023  # Used within this native test iteration.
                                listing.getResult = lambda: -1
                            return listing
                        with patch.object(clnch_cmdlist, "CommandListWindow", side_effect=create), \
                             patch.object(clnch_cmdlist.clnch_misc, "adjustWindowPosition",
                                          side_effect=fail if stage == "position" else lambda *a, **kw: None), \
                             patch.object(self.window, "activate", side_effect=fail if stage == "activate" else self.window.activate), \
                             self.assertRaisesRegex(RuntimeError, stage):
                            clnch_cmdlist.open_list(self.window, on_edit=fail if stage == "edit" else self.ui._open_command_editor)
                        self.assertTrue(self.window.isEnabled())
                        self.assertEqual(len(handles), 1)
                        self.assertFalse(user32.IsWindow(handles[0]))

            def test_native_ipc_execute_runs_commands_once_and_preserves_input(self):
                registered_output = data / "ipc-registered.json"
                system_output = data / "ipc-system.json"
                self.apply({"ipc-alias": {"target": {"link": "ipc-child", "args": '"fixed arg"'}},
                            "ipc-child": {"target": self.probe_action(registered_output)}})
                calls = []
                self.window.launcher.command_list.append(("ipc-probe", lambda info: calls.append((list(info.args), info.mod))))
                self.window.input_settings["HISTORY_MODE"] = "session"
                self.window.commandline_history = ["history sentinel"]
                ipc = clnch_ipc.IpcData()
                for text in ('ipc-probe;日本語 "two words" "" tail\\', 'ipc-alias;  "dynamic arg" ""  ',
                             "pythonw;" + subprocess.list2cmdline(["-B", "-S", str(probe), str(system_output), "OS arg", ""])):
                    ipc.trySetOption("--execute", text)
                def receive():
                    edit = self.window.commandline_edit
                    selection = edit.getSelection()
                    with subprocess.Popen([sys.executable, "-B", "-S", "-c", IPC_SENDER,
                            station_name.value, str(self.window.getHWND()), ipc.getValue()],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE) as sender:
                        try:
                            self.pump(lambda: sender.poll() is not None, timeout=8)
                        finally:
                            if sender.poll() is None:
                                sender.kill()
                            stdout, stderr = sender.communicate(timeout=2)
                        self.assertEqual(sender.returncode, 0, (stdout, stderr))
                    self.assertEqual(calls, [(["日本語", "two words", "", "tail\\"], 0)])
                    self.assertIs(self.window.commandline_edit, edit)
                    self.assertEqual(edit.getText(), "keep input;日本語")
                    self.assertEqual(edit.getSelection(), selection)
                    self.assertEqual(self.window.commandline_history, ["history sentinel"])
                shell = clnch_mainwindow.pyauto.shellExecute
                with (patch.dict(os.environ, PATH=str(pythonw.parent)),
                      patch.object(clnch_mainwindow.pyauto, "shellExecute", wraps=shell) as launched):
                    self.input_action("keep input;日本語", receive)
                    self.assertEqual(self.result(registered_output)["args"], ["fixed arg", "dynamic arg", ""])
                    self.assertEqual(self.result(system_output)["args"], ["OS arg", ""])
                    self.assertEqual(launched.call_count, 2)
                    self.assertEqual(launched.call_args_list[0].args[2],
                        self.probe_action(registered_output)["args"] + ' "fixed arg"   "dynamic arg" ""  ')
                self.assertEqual(self.window.commandline_history, ["history sentinel"])

            def test_native_ipc_argument_selection_and_replacement(self):
                self.window.input_settings["COMPLETION_MODE"] = "off"
                self.window.commandline_history = ["history sentinel"]
                cases = (
                    ("command;arg", [8, 8], [8, 11]),
                    ("command", [7, 7], [7, 7]),
                    ("", [0, 0], [0, 0]),
                    ("command;", [8, 8], [8, 8]),
                    (";abc", [1, 1], [1, 4]),
                    ("command;arg1;arg2", [8, 8], [8, 17]),
                    ("https://x/a;b;c", [12, 12], [12, 15]),
                    (' 日本語; "a b";  ', [5, 5], [5, 14]),
                )
                for text, caret, arguments in cases:
                    for mode, expected in (("3", caret), ("4", arguments)):
                        with self.subTest(text=text, selection=mode):
                            ipc = clnch_ipc.IpcData()
                            ipc.trySetOption("--text", text)
                            ipc.trySetOption("--selection", mode)
                            errors, observed = [], []
                            def drive(text=text, expected=expected, errors=errors, observed=observed):
                                edit = self.window.commandline_edit
                                if edit is None:
                                    return
                                self.window.killTimer(drive)
                                try:
                                    observed.append(True)
                                    self.assertEqual(edit.getText(), text)
                                    self.assertEqual(edit.getSelection(), expected)
                                    self.assertTrue(all(0 <= value <= len(text) for value in edit.getSelection()))
                                    user32.SendMessageW(self.window.getHWND(), 0x0102, ord("X"), 1)
                                    self.assertEqual(edit.getText(), text[:expected[0]] + "X" + text[expected[1]:])
                                    self.assertEqual(edit.getSelection(), [expected[0] + 1] * 2)
                                except BaseException as error:  # noqa: BLE001  # Surface timer assertions and leave the native input loop.
                                    errors.append(error)
                                finally:
                                    self.window.quit()
                            self.window.setTimer(drive, 30)
                            try:
                                with subprocess.Popen([sys.executable, "-B", "-S", "-c", IPC_SENDER,
                                        station_name.value, str(self.window.getHWND()), ipc.getValue()],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE) as sender:
                                    try:
                                        self.pump(lambda: sender.poll() is not None, timeout=8)
                                    finally:
                                        if sender.poll() is None:
                                            sender.kill()
                                        stdout, stderr = sender.communicate(timeout=2)
                                    self.assertEqual(sender.returncode, 0, (stdout, stderr))
                            finally:
                                self.window.killTimer(drive)
                            self.assertEqual(errors, [])
                            self.assertEqual(observed, [True])
                            self.assertIsNone(self.window.commandline_edit)
                            self.assertEqual(self.window.commandline_history, ["history sentinel"])

            def test_native_ipc_position_without_foreground_keeps_input_and_resets(self):
                self.assertIsNone(clnch_ipc.pyauto.Window.getForeground())
                self.window.resetPos()
                saved = self.window.getWindowRect()[:2]
                current = (saved[0] + 37, saved[1] + 41)
                self.window.setPosSize(*current, self.window.width(), self.window.height(), 0)
                self.window.commandline_history = ["history sentinel"]
                ipc = clnch_ipc.IpcData()
                ipc.trySetOption("--text", "command;日本語")
                ipc.trySetOption("--selection", "4")
                ipc.trySetOption("--position", "(50,25)")
                errors, observed = [], []
                def drive():
                    edit = self.window.commandline_edit
                    if edit is None:
                        return
                    self.window.killTimer(drive)
                    try:
                        observed.append(True)
                        self.assertEqual(self.window.getWindowRect()[:2], current)
                        self.assertEqual(edit.getText(), "command;日本語")
                        self.assertEqual(edit.getSelection(), [8, 11])
                        user32.SendMessageW(self.window.getHWND(), 0x0102, ord("X"), 1)
                        self.assertEqual(edit.getText(), "command;X")
                    except BaseException as error:  # noqa: BLE001  # Surface timer assertions and leave the native input loop.
                        errors.append(error)
                    finally:
                        self.window.quit()
                self.window.setTimer(drive, 30)
                try:
                    with subprocess.Popen([sys.executable, "-B", "-S", "-c", IPC_SENDER,
                            station_name.value, str(self.window.getHWND()), ipc.getValue()],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE) as sender:
                        try:
                            self.pump(lambda: sender.poll() is not None, timeout=8)
                        finally:
                            if sender.poll() is None:
                                sender.kill()
                            stdout, stderr = sender.communicate(timeout=2)
                        self.assertEqual(sender.returncode, 0, (stdout, stderr))
                finally:
                    self.window.killTimer(drive)
                self.assertEqual(errors, [])
                self.assertEqual(observed, [True])
                self.assertIsNone(self.window.commandline_edit)
                self.assertEqual(self.window.commandline_history, ["history sentinel"])
                self.assertEqual(self.window.getWindowRect()[:2], saved)

            def test_native_ipc_new_waits_for_modal_close_then_runs_next_execute(self):
                ipc = clnch_ipc.IpcData()
                ipc.trySetOption("--execute", "new")
                ipc.trySetOption("--execute", "ipc-after")
                observed, calls = [], []
                self.window.launcher.command_list.append(("ipc-after", lambda info: calls.append("after")))
                original_loop = ckit.TextWindow.messageLoop
                def message_loop(child, *args):
                    if isinstance(child, clnch_cmdeditor.CommandEditor):
                        def dismiss():
                            child.killTimer(dismiss)
                            observed.append((sender.poll() is None, list(calls), self.window.isEnabled()))
                            child._on_cancel()
                        child.setTimer(dismiss, 200)
                    return original_loop(child, *args)
                with subprocess.Popen([sys.executable, "-B", "-S", "-c", IPC_SENDER,
                        station_name.value, str(self.window.getHWND()), ipc.getValue()],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE) as sender:
                    try:
                        with patch.object(ckit.TextWindow, "messageLoop", message_loop):
                            self.pump(lambda: sender.poll() is not None, timeout=8)
                    finally:
                        if sender.poll() is None:
                            sender.kill()
                        stdout, stderr = sender.communicate(timeout=2)
                    self.assertEqual(sender.returncode, 0, (stdout, stderr))
                self.assertEqual(observed, [(True, [], False)])
                self.assertEqual(calls, ["after"])
                self.assertTrue(self.window.isEnabled())

            def test_native_ipc_modal_builtins_preserve_owner_and_continue_execution(self):
                output = data / "ipc-modal-child.json"
                self.apply({"alias-config": {"target": {"link": "config"}},
                            "alias-new": {"target": {"link": "new"}},
                            "alias-reload": {"target": {"link": "reload"}},
                            "alias-quit": {"target": {"link": "quit"}},
                            "external": {"target": self.probe_action(output)}})
                calls, nested, errors = [], [], []
                self.window.launcher.command_list.append(("ipc-probe", lambda info: calls.append(list(info.args))))
                self.window.commandline_history = ["history sentinel"]
                custom = self.window.custom
                launcher_commands = self.window.launcher.command_list
                original_loop = ckit.TextWindow.messageLoop
                active_child = [None]
                child_handles = []

                def message_loop(child, *args):
                    if child is self.window:
                        return original_loop(child, *args)
                    if active_child[0] is None:
                        active_child[0] = child
                        def drive():
                            child.killTimer(drive)
                            receive(child)
                        child.setTimer(drive, 30)
                    elif child is not active_child[0]:
                        nested.append(child.getHWND())
                        if hasattr(child, "_on_cancel"):
                            child._on_cancel()
                        else:
                            child.cancel()
                        return None
                    return original_loop(child, *args)

                def receive(child):
                    active_child[0] = child
                    ipc = clnch_ipc.IpcData()
                    for text in ("config", "new", "history", "alias-config", "alias-new",
                                 "quit", "alias-quit", "reload", "alias-reload", "external", "ipc-probe;after"):
                        ipc.trySetOption("--execute", text)
                    for option, value in (("--text", "replace"), ("--selection", "A"), ("--position", "(50, 50)")):
                        ipc.trySetOption(option, value)
                    before = self.window.getWindowRect()
                    edit = self.window.commandline_edit
                    input_before = (edit.getText(), edit.getSelection())
                    user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
                    user32.GetWindow.restype = wintypes.HWND
                    child_handles.append(child.getHWND())
                    owner = user32.GetWindow(child.getHWND(), 4)
                    self.assertEqual(owner, self.window.getHWND())
                    user32.GetFocus.restype = wintypes.HWND
                    focus = user32.GetFocus()
                    try:
                        with subprocess.Popen([sys.executable, "-B", "-S", "-c", IPC_SENDER,
                                station_name.value, str(self.window.getHWND()), ipc.getValue()],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE) as sender:
                            try:
                                deadline = time.monotonic() + 8
                                original_loop(child, lambda: sender.poll() is None and time.monotonic() < deadline)
                            finally:
                                if sender.poll() is None:
                                    sender.kill()
                                stdout, stderr = sender.communicate(timeout=2)
                            self.assertEqual(sender.returncode, 0, (stdout, stderr))
                        self.assertEqual(nested, [])
                        self.assertFalse(self.window.isEnabled())
                        self.assertTrue(child.isEnabled())
                        self.assertIs(self.window.custom, custom)
                        self.assertIs(self.window.launcher.command_list, launcher_commands)
                        self.assertFalse(self.window.quit_requested)
                        self.assertEqual(self.window.getWindowRect(), before)
                        self.assertIs(self.window.commandline_edit, edit)
                        self.assertEqual((edit.getText(), edit.getSelection()), input_before)
                        self.assertEqual(user32.GetWindow(child.getHWND(), 4), owner)
                        self.assertEqual(user32.GetFocus(), focus)
                        self.assertEqual(calls, [["after"]])
                        self.assertEqual(self.window.commandline_history, ["history sentinel"])
                    except BaseException as error:  # noqa: BLE001  # Close native modal loops before surfacing assertions.
                        errors.append(error)
                    finally:
                        if hasattr(child, "_on_cancel"):
                            child._on_cancel()
                        else:
                            child.cancel()

                for name, opener in (("editor", self.ui._open_command_editor),
                                     ("config", lambda: self.window.command_ConfigMenu(None)),
                                     ("commands", lambda: clnch_cmdlist.open_list(self.window))):
                    with self.subTest(screen=name):
                        active_child[0] = None
                        calls.clear()
                        output.unlink(missing_ok=True)
                        with patch.object(ckit.TextWindow, "messageLoop", message_loop):
                            self.input_action("keep input;日本語", opener)
                        self.assertEqual(errors, [])
                        self.assertTrue(self.window.isEnabled())
                        user32.IsWindow.argtypes = (wintypes.HWND,)
                        self.assertFalse(user32.IsWindow(child_handles[-1]))
                        self.assertEqual(self.result(output)["args"], [])

            def test_native_ipc_delivery_while_editor_is_modal(self):
                ipc = clnch_ipc.IpcData()
                ipc.trySetOption("--text", "IPC日本語")
                def receive(editor):
                    with subprocess.Popen([sys.executable, "-B", "-S", "-c", IPC_SENDER,
                            station_name.value, str(self.window.getHWND()), ipc.getValue()],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE) as sender:
                        deadline = time.monotonic() + 8
                        editor.messageLoop(lambda: sender.poll() is None and time.monotonic() < deadline)
                        if sender.poll() is None:
                            sender.kill()
                        stdout, stderr = sender.communicate(timeout=2)
                        self.assertEqual(sender.returncode, 0, (stdout, stderr))
                    self.assertFalse(self.window.isEnabled())
                    self.assertIsNone(self.window.commandline_edit)
                    editor._on_keydown(ckit.VK_ESCAPE, 0)
                original = clnch_ipc.IpcData.commandLine
                with patch.object(clnch_ipc.IpcData, "commandLine", autospec=True, side_effect=original) as delivered:
                    self.run_editor(receive)
                delivered.assert_called_once()
                received, parent = delivered.call_args.args
                self.assertIs(parent, self.window)
                self.assertEqual(json.loads(received.ini.get("COMMANDLINE", "text")), "IPC日本語")

        try:
            suite = (unittest.TestSuite(NativeCommandChecks(name) for name in sys.argv[1:])
                     if sys.argv[1:] else unittest.defaultTestLoader.loadTestsFromTestCase(NativeCommandChecks))
            result = unittest.TextTestRunner(verbosity=2).run(suite)
        finally:
            ckit.JobQueue.cancelAll()
            ckit.JobQueue.joinAll()
            ckit.JobQueue.defaultQueue().destroy()
            os.chdir(ROOT)
        if desktop_handles and result.wasSuccessful():
            print("Foreground checks used temporary windows/settings and restored foreground; no user clipboard writes."
                  if interactive_foreground else "Native checks used a private station; user clipboard/desktop were untouched.")
        faulthandler.cancel_dump_traceback_later()
        return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
