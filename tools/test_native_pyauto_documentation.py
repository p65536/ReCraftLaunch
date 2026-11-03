"""Check native pyauto documentation without sending OS input or installing hooks."""
import ctypes
import faulthandler
import re
import unittest
from contextlib import ExitStack
from ctypes import wintypes

from test_native_shell import CALL, ROOT, P, replace_import

import pyauto


class MouseInput(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("data", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("extra", ctypes.c_size_t)]
class KeyboardInput(ctypes.Structure):
    _fields_ = [("vk", wintypes.WORD), ("scan", wintypes.WORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD), ("extra", ctypes.c_size_t)]
class EventData(ctypes.Union):
    _fields_ = [("mouse", MouseInput), ("key", KeyboardInput)]
class InputEvent(ctypes.Structure):
    _fields_ = [("kind", wintypes.DWORD), ("value", EventData)]


class NativePyautoDocumentationTests(unittest.TestCase):
    def test_input_preparation(self):
        captured, errors = [], []
        def send(count, pointer, size):
            try:
                self.assertEqual(size, ctypes.sizeof(InputEvent))
                captured.extend((InputEvent * count).from_buffer_copy(ctypes.string_at(pointer, count * size)))
            except BaseException as error:  # noqa: BLE001  # Report assertions outside the native callback.
                errors.append(error)
            return count
        events = [pyauto.KeyDown("A"), pyauto.KeyUp("A"), pyauto.Key("A"), pyauto.Char("A"),
                  pyauto.MouseMove(10, 20), pyauto.MouseLeftDown(10, 20), pyauto.MouseLeftUp(10, 20),
                  pyauto.MouseLeftClick(10, 20), pyauto.MouseRightDown(10, 20), pyauto.MouseRightUp(10, 20),
                  pyauto.MouseRightClick(10, 20), pyauto.MouseMiddleDown(10, 20), pyauto.MouseMiddleUp(10, 20),
                  pyauto.MouseMiddleClick(10, 20), pyauto.MouseWheel(10, 20, -0.5),
                  pyauto.MouseHorizontalWheel(10, 20, 1.0), pyauto.Char("\U0001f600")]
        with replace_import("SendInput", CALL(wintypes.UINT, wintypes.UINT, P, ctypes.c_int)(send),
                            module=pyauto.pyautocore):
            pyauto.Input.send(events)
        self.assertEqual(errors, [])
        self.assertEqual(len(captured), 23)
        self.assertEqual([event.value.key.flags for event in captured[:6]], [0, 2, 0, 2, 4, 6])
        self.assertEqual(captured[-2].value.key.scan, 0xf600)
        self.assertEqual(captured[-4].value.mouse.flags, 0x8800)
        self.assertEqual(ctypes.c_int32(captured[-4].value.mouse.data).value, -60)
        self.assertEqual(captured[-3].value.mouse.flags, 0x9000)
        self.assertEqual(captured[-3].value.mouse.data, 120)


    def test_virtual_desktop_mouse_coordinates(self):
        helpers = (pyauto.MouseMove, pyauto.MouseLeftDown, pyauto.MouseLeftUp,
                   pyauto.MouseLeftClick, pyauto.MouseRightDown, pyauto.MouseRightUp,
                   pyauto.MouseRightClick, pyauto.MouseMiddleDown, pyauto.MouseMiddleUp,
                   pyauto.MouseMiddleClick)
        for left, top, width, height in ((0, 0, 1920, 1080), (-1920, -1080, 4480, 2520),
                                         (-1, -1, 1, 1)):
            metrics = {76: left, 77: top, 78: width, 79: height}
            captured = []
            def send(count, pointer, size, captured=captured):
                captured.extend((InputEvent * count).from_buffer_copy(ctypes.string_at(pointer, count * size)))
                return count
            with self.subTest(metrics=metrics), ExitStack() as stack:
                stack.enter_context(replace_import("GetSystemMetrics", CALL(ctypes.c_int, ctypes.c_int)(
                    lambda index, metrics=metrics: metrics[index]), module=pyauto.pyautocore))
                stack.enter_context(replace_import("SendInput", CALL(wintypes.UINT, wintypes.UINT, P, ctypes.c_int)(send),
                    module=pyauto.pyautocore))
                for x, y in ((left, top), (left + width - 1, top + height - 1), (0, 0),
                             (left + width // 2, top + height // 2), (-2**31, -2**31),
                             (2**31 - 1, 2**31 - 1)):
                    captured.clear()
                    pyauto.Input.send([helper(x, y) for helper in helpers])
                    expected_x = max(left, min(x, left + width - 1))
                    expected_y = max(top, min(y, top + height - 1))
                    self.assertEqual(len(captured), 13)
                    for event in captured:
                        mouse = event.value.mouse
                        self.assertEqual(mouse.flags & 0xc001, 0xc001)
                        self.assertEqual(left + mouse.dx * width // 65536, expected_x)
                        self.assertEqual(top + mouse.dy * height // 65536, expected_y)
                captured.clear()
                pyauto.Input.send([pyauto.MouseWheel(-10, -20, -0.5),
                                   pyauto.MouseHorizontalWheel(-10, -20, 1.0)])
                self.assertEqual([event.value.mouse.flags for event in captured], [0x8800, 0x9000])

    def test_hook_cleanup(self):
        source = (ROOT / "pyauto/pyautocore/pyautocore.cpp").read_text(encoding="utf-8-sig")
        recipes = re.findall(r"@code\{\.py\}\n(.*?)@endcode", source, re.DOTALL)
        self.assertEqual(len(recipes), 2)
        self.assertEqual(recipes[0], recipes[1])
        namespace = {}
        exec(compile(recipes[0], "pyautocore.cpp:release_hook", "exec"), namespace)  # noqa: S102  # Exercise the documented recipe directly.
        unhooked = []
        with ExitStack() as stack:
            stack.enter_context(replace_import("SetWindowsHookExW", CALL(P, ctypes.c_int, P, P, wintypes.DWORD)(
                lambda kind, proc, module, thread: kind), module=pyauto.pyautocore))
            stack.enter_context(replace_import("UnhookWindowsHookEx", CALL(wintypes.BOOL, P)(
                lambda handle: unhooked.append(handle) or 1), module=pyauto.pyautocore))
            hook = pyauto.Hook()
            try:
                hook.keydown = lambda vk, scan: None
                hook.mousemove = lambda x, y: None
                hook.clipboard = lambda: None
                namespace["release_hook"](hook)
                self.assertEqual(set(unhooked), {13, 14})
                for name in ("keydown", "keyup", "mousedown", "mouseup", "mousedblclk", "mousemove",
                             "mousewheel", "mousehorizontalwheel", "clipboard"):
                    self.assertIsNone(getattr(hook, name))
            finally:
                hook.destroy()


if __name__ == "__main__":
    faulthandler.dump_traceback_later(30, exit=True)
    unittest.main(verbosity=2)
