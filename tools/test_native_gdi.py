"""Real offscreen GDI lifetime/pixel checks on a private desktop; no visual assessment."""
import ctypes as c
import sys
import unittest
from contextlib import ExitStack, contextmanager
from ctypes import wintypes as w
from pathlib import Path

import native_test_support

if "--package" in sys.argv:
    index = sys.argv.index("--package")
    native_test_support.RUN_DIR = Path(sys.argv[index + 1]).resolve()
    del sys.argv[index:index + 2]

import test_window_show
from test_native_shell import CALL, P, imports, replace_import

import ckit
from ckit import ckitcore

gdi = c.WinDLL("gdi32")
user = c.WinDLL("user32")
kernel = c.WinDLL("kernel32")
for name in ("GetObjectType", "DeleteObject", "DeleteDC"):
    getattr(gdi, name).argtypes = (P,)
    getattr(gdi, name).restype = w.DWORD
gdi.GetCurrentObject.argtypes = (P, w.UINT)
gdi.GetCurrentObject.restype = P
gdi.SelectObject.argtypes = (P, P)
gdi.SelectObject.restype = P
gdi.GetStockObject.argtypes = (c.c_int,)
gdi.GetStockObject.restype = P
gdi.GdiFlush.argtypes = ()
gdi.GdiFlush.restype = w.BOOL
gdi.GetObjectW.argtypes = (P, c.c_int, P)
gdi.GetObjectW.restype = c.c_int
kernel.GetCurrentProcess.restype = P
user.GetGuiResources.argtypes = (P, w.DWORD)
user.GetGuiResources.restype = w.DWORD


def gdi_count():
    gdi.GdiFlush()
    return user.GetGuiResources(kernel.GetCurrentProcess(), 0)


class Bitmap(c.Structure):
    _fields_ = [("kind", w.LONG), ("width", w.LONG), ("height", w.LONG),
               ("stride", w.LONG), ("planes", w.WORD), ("depth", w.WORD), ("bits", P)]


@contextmanager
def plane_pixels():
    snapshots = []
    blend = CALL(w.BOOL, P, c.c_int, c.c_int, c.c_int, c.c_int,
                 P, c.c_int, c.c_int, c.c_int, c.c_int, w.DWORD)
    real = blend(c.cast(c.WinDLL("msimg32").AlphaBlend, P).value)

    def capture(*args):
        bitmap = Bitmap()
        handle = gdi.GetCurrentObject(args[5], 7)
        if gdi.GetObjectW(handle, c.sizeof(bitmap), c.byref(bitmap)) and bitmap.bits:
            gdi.GdiFlush()
            snapshots.append((bitmap.width, bitmap.height,
                              c.string_at(bitmap.bits, bitmap.stride * bitmap.height)))
        return real(*args)

    with replace_import("AlphaBlend", blend(capture), ckitcore):
        yield snapshots


@contextmanager
def audit_gdi(fail=None):
    """Observe actual selections/deletions; optionally fail one allocation/selection/draw."""
    dcs, created, deleted, errors, failed = set(), [], [], [], []
    selections, calls = {}, {}
    fault_name, fault_number = fail if isinstance(fail, tuple) else (fail, 1)

    def should_fail(name):
        calls[name] = calls.get(name, 0) + 1
        if name == fault_name and calls[name] == fault_number:
            failed.append(fail)
            return True
        return False
    signatures = {
        "CreateSolidBrush": CALL(P, w.DWORD),
        "CreatePen": CALL(P, c.c_int, c.c_int, w.DWORD),
        "Rectangle": CALL(w.BOOL, P, c.c_int, c.c_int, c.c_int, c.c_int),
    }
    if "ExtCreatePen" in imports(ckitcore):
        signatures["ExtCreatePen"] = CALL(P, w.DWORD, w.DWORD, P, w.DWORD, P)
    with ExitStack() as stack:
        for name, signature in signatures.items():
            real = signature(c.cast(getattr(gdi, name), P).value)

            def invoke(*args, name=name, real=real):
                if should_fail(name):
                    return 0
                result = real(*args)
                if result and name != "Rectangle":
                    created.append(result)
                return result

            stack.enter_context(replace_import(name, signature(invoke), ckitcore))

        def select(dc, obj):
            dcs.add(dc)
            if obj in created and should_fail("SelectObject"):
                return None
            previous = gdi.SelectObject(dc, obj)
            if previous and obj in created:
                selections[obj] = dc, previous
            return previous

        def delete(obj):
            kind = gdi.GetObjectType(obj)
            if kind in (1, 2, 6, 7, 11):
                for dc in dcs:
                    if gdi.GetCurrentObject(dc, 1 if kind == 11 else kind) == obj:
                        errors.append(("selected at DeleteObject", kind, obj))
            elif kind == 10:
                errors.append(("DeleteObject used for memory DC", obj))
            result = gdi.DeleteObject(obj)
            if obj in created:
                if obj in selections:
                    dc, previous = selections.pop(obj)
                    if gdi.GetCurrentObject(dc, 1 if kind == 11 else kind) != previous:
                        errors.append(("original selection not restored", kind, obj))
                deleted.append(obj)
                if not result:
                    errors.append(("DeleteObject failed", obj))
            return result

        stack.enter_context(replace_import("SelectObject", CALL(P, P, P)(select), ckitcore))
        stack.enter_context(replace_import("DeleteObject", CALL(w.BOOL, P)(delete), ckitcore))
        yield created, deleted, errors, failed


class NativeGdiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ckit.registerWindowClass("ReCLGdiLifetimeTest")
        assert Path(ckitcore.__file__).resolve() == native_test_support.RUN_DIR / "lib/ckitcore.pyd"
        print("ckitcore:", ckitcore.__file__, flush=True)

    def setUp(self):
        self.font = ckit.Font("Consolas", 16)
        self.cw, self.ch = self.font.getCharSize()
        self.window = ckit.Window(x=0, y=0, width=self.cw * 8, height=self.ch * 4,
                                  show=False, bg_color=(9, 19, 29))
        self.addCleanup(lambda: self.window and self.window.destroy())
        self.plane = ckit.TextPlane(self.window, (0, 0), (self.cw * 8, self.ch * 4), 0)
        self.plane.setFont(self.font)
        self.serial = 0

    def paint(self, attr):
        self.serial += 1
        # Alternate attributes so every iteration really redraws, rather than hitting dirty/cache.
        self.plane.putString(0, 0, 8, 1, attr, " " * 8)
        self.plane.putString(0, 1, 8, 1, ckit.Attribute(bg=(self.serial % 255, 2, 3)), " " * 8)
        self.window.flushPaint()

    def pixel(self, x, y):
        buffer = test_window_show.WindowShowTests.buffer(self, self.window)
        gdi.GetPixel.argtypes = (P, c.c_int, c.c_int)
        gdi.GetPixel.restype = w.DWORD
        value = gdi.GetPixel(buffer.dc, x, y)
        return value & 255, (value >> 8) & 255, (value >> 16) & 255

    def attributes(self):
        edges = ckit.LINE_LEFT | ckit.LINE_RIGHT | ckit.LINE_TOP | ckit.LINE_BOTTOM
        for background in ({}, {"bg": (40, 50, 60)}, {"bg_gradation": ((20, 30, 40),) * 4}):
            for lines in ({}, {"line0": (edges, (100, 110, 120))},
                          {"line0": (edges | ckit.LINE_DOT, (100, 110, 120))},
                          {"line1": (edges, (200, 210, 220))},
                          {"line1": (edges | ckit.LINE_DOT, (200, 210, 220))},
                          {"line0": (edges | ckit.LINE_DOT, (100, 110, 120)),
                           "line1": (edges, (200, 210, 220))},
                          {"line0": (edges, (100, 110, 120)),
                           "line1": (edges | ckit.LINE_DOT, (200, 210, 220))}):
                yield ckit.Attribute(fg=(255, 255, 255), **background, **lines)

    def test_restore_before_delete_all_backgrounds_and_line_slots(self):
        with audit_gdi() as (created, deleted, errors, _):
            for attr in self.attributes():
                self.paint(attr)
            self.window.destroy()
            self.window = None
        self.assertTrue(created)
        self.assertCountEqual(created, deleted)
        self.assertEqual(errors, [])

    def test_allocation_selection_and_rectangle_failures_release_acquired_objects(self):
        edges = ckit.LINE_LEFT | ckit.LINE_BOTTOM
        for fail in ("CreateSolidBrush", "CreatePen", ("CreatePen", 2),
                     *(("SelectObject", i) for i in range(1, 5)), "Rectangle"):
            with self.subTest(fail=fail):
                attr = ckit.Attribute(bg=(40, 50, 60), line0=(edges, (100, 110, 120)),
                                      line1=(edges | ckit.LINE_DOT, (200, 210, 220)))
                # Force the main row dirty even after a failed Rectangle.
                self.plane.putString(0, 0, 8, 1, ckit.Attribute(), "clear")
                with audit_gdi(fail) as (created, deleted, errors, failed):
                    self.paint(attr)
                self.assertEqual(failed, [fail])
                self.assertCountEqual(created, deleted)
                self.assertEqual(errors, [])

    def test_lines_allocate_no_gdi_objects_without_flat_background(self):
        edges = ckit.LINE_LEFT | ckit.LINE_RIGHT | ckit.LINE_TOP | ckit.LINE_BOTTOM
        for background in ({}, {"bg_gradation": ((20, 30, 40),) * 4}):
            for dotted in (False, True):
                attr = ckit.Attribute(**background, line0=(edges, (100, 110, 120)),
                                      line1=(edges | (ckit.LINE_DOT if dotted else 0), (200, 210, 220)))
                self.plane.putString(0, 0, 8, 1, attr, " " * 8)
                with audit_gdi() as (created, _, errors, _):
                    self.window.flushPaint()
                self.assertEqual(created, [])
                self.assertEqual(errors, [])

    def test_background_line_pixels_and_cached_redraw(self):
        edges = ckit.LINE_LEFT | ckit.LINE_RIGHT | ckit.LINE_TOP | ckit.LINE_BOTTOM
        for bg, expected in (({}, (9, 19, 29)), ({"bg": (40, 50, 60)}, (40, 50, 60)),
                             ({"bg_gradation": ((20, 30, 40),) * 4}, (20, 30, 40))):
            for dotted in (False, True):
                with self.subTest(bg=bg, dotted=dotted):
                    self.paint(ckit.Attribute(**bg, line0=(edges | (ckit.LINE_DOT if dotted else 0),
                                                          (100, 110, 120))))
                    self.assertEqual(self.pixel(3, 3), expected)
                    self.assertEqual(self.pixel(0, 0), (100, 110, 120))
                    self.assertEqual(self.pixel(1, 0), expected if dotted else (100, 110, 120))
                    for x, y in ((0, 2), (2, self.ch - 1), (self.cw * 8 - 1, 2)):
                        self.assertEqual(self.pixel(x, y), (100, 110, 120))
                    for x, y in ((0, 3), (3, self.ch - 1), (self.cw * 8 - 1, 3)):
                        self.assertEqual(self.pixel(x, y), expected if dotted else (100, 110, 120))
                    with audit_gdi() as (created, _, errors, _):
                        self.window.flushPaint()
                    self.assertEqual(created, [])
                    self.assertEqual(errors, [])
                    self.assertEqual(self.pixel(3, 3), expected)

    def test_alpha_gradient_and_both_line_slots_in_source_bitmap(self):
        def pixel(snapshot, x, y):
            width, height, data = snapshot
            offset = ((height - y - 1) * width + x) * 4
            b, g, r, a = data[offset:offset + 4]
            return r, g, b, a

        gradient = ((20, 30, 40), (180, 30, 40), (20, 190, 40), (180, 190, 40))
        for bg, center in (({}, (0, 0, 0, 0)), ({"bg": (40, 50, 60)}, (40, 50, 60, 255)),
                           ({"bg_gradation": gradient}, None)):
            with self.subTest(bg=bg), plane_pixels() as snapshots:
                self.paint(ckit.Attribute(**bg, line0=(ckit.LINE_TOP, (100, 110, 120)),
                                         line1=(ckit.LINE_TOP | ckit.LINE_DOT, (200, 210, 220))))
                self.assertEqual(len(snapshots), 1)
                source = snapshots[0]
                self.assertEqual(pixel(source, 0, 0), (200, 210, 220, 255))
                self.assertEqual(pixel(source, 1, 0), (100, 110, 120, 255))
                if center:
                    self.assertEqual(pixel(source, 3, 3), center)
                else:
                    left, right = pixel(source, 2, 3), pixel(source, self.cw * 8 - 3, 3)
                    bottom = pixel(source, 2, self.ch - 3)
                    self.assertLess(left[0], right[0])
                    self.assertLess(left[1], bottom[1])
                    self.assertEqual((left[2:], right[2:], bottom[2:]), ((40, 255),) * 3)

    def test_hidden_and_fontless_planes_allocate_no_drawing_objects(self):
        self.plane.show(False)
        with audit_gdi() as (created, _, errors, _):
            self.paint(ckit.Attribute(bg=(40, 50, 60)))
        self.assertEqual(created, [])
        self.assertEqual(errors, [])
        plane = ckit.TextPlane(self.window, (0, 0), (40, 20), -1)
        with audit_gdi() as (created, _, errors, _):
            self.window.flushPaint()
        self.assertEqual(created, [])
        self.assertEqual(errors, [])
        plane.setFont(self.font)
        plane.putString(0, 0, 1, 1, ckit.Attribute(bg=(60, 70, 80)), " ")
        self.window.flushPaint()
        self.assertEqual(self.pixel(2, 2), (60, 70, 80))

    def test_repeated_draw_resize_and_destroy_has_bounded_gdi_count(self):
        attrs = list(self.attributes())
        counts = []
        for batch in range(7):
            for i in range(240):
                width = self.cw * (8 + i % 2)
                self.window.setPositionAndSize(0, 0, width, self.ch * 4, 0)
                self.plane.setSize((width, self.ch * 4))
                self.paint(attrs[i % len(attrs)])
            counts.append(gdi_count())
        print("GDI draw/resize (7 x 240):", counts, flush=True)
        self.assertLessEqual(max(counts) - min(counts), 2)
        self.window.destroy()
        self.window = None
        baseline = gdi_count()
        counts = []
        for _ in range(30):
            window = ckit.TextWindow(x=0, y=0, width=12, height=3, show=False,
                                      font=self.font)
            window.putString(0, 0, 12, 1, ckit.Attribute(bg=(30, 40, 50)), "draw 日本語")
            window.flushPaint()
            window.destroy()
            counts.append(gdi_count())
        print("GDI create/destroy:", baseline, min(counts), max(counts), counts[-1], flush=True)
        self.assertLessEqual(max(counts), baseline + 2)


if __name__ == "__main__":
    unittest.main()
