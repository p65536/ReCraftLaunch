"""Fault injection for modal ownership; all windows and GUI operations are doubles."""
import ast
import sys
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


def load_functions(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8-sig"))
    nodes = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names}
    exec(compile(ast.Module(body=list(nodes.values()), type_ignores=[]), str(path), "exec"), namespace)  # noqa: S102  # Execute actual functions with isolated GUI doubles.


_cleanup_namespace = {"_contextmanager": contextmanager}
load_functions("ckit/ckit_misc.py", {"_cleanup_on_exit"}, _cleanup_namespace)
_cleanup_on_exit = _cleanup_namespace["_cleanup_on_exit"]
_cleanup_namespace["_ExitStack"] = ExitStack
load_functions("clnch/clnch_misc.py", {"_modal_dialog_scope"}, _cleanup_namespace)
_modal_dialog_scope = _cleanup_namespace["_modal_dialog_scope"]
load_functions("clnch/clnch_misc.py", {"_require_data_path"}, _cleanup_namespace)
_require_data_path = _cleanup_namespace["_require_data_path"]
load_functions("clnch/clnch_listwindow.py", {"_split_list_result"}, _cleanup_namespace)
_split_list_result = _cleanup_namespace["_split_list_result"]


class ModalLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.failures = {}
        self.children = []
        self.enabled = True
        self.saved = False
        self.result = 0
        self.parent = SimpleNamespace(
            centerOfWindowInPixel=lambda: (10, 20),
            getWindowRect=lambda: (0, 0, 100, 100),
            isEnabled=lambda: self.enabled,
            enable=self.enable,
            activate=lambda: self.step("activate"),
        )
        self.namespace = {"ExitStack": ExitStack, "_contextmanager": contextmanager, "sys": sys}
        load_functions("ckit/ckit_misc.py", {"_cleanup_on_exit"}, self.namespace)
        self.namespace.update(
            ListWindow=self.child, CommandEditor=self.child,
            clnch_misc=SimpleNamespace(_modal_dialog_scope=_modal_dialog_scope,
                                      adjustWindowPosition=lambda *a, **kw: self.step("position")),
        )
        load_functions("clnch/clnch_listwindow.py", {"popMenu"}, self.namespace)
        load_functions("clnch/clnch_cmdeditor.py", {"open_editor"}, self.namespace)

    def step(self, name):
        self.events.append(name)
        if name in self.failures:
            raise self.failures[name]

    def enable(self, value):
        self.enabled = value  # Model a setter which changes state before raising.
        self.step("enable" if value else "disable")

    def child(self, *args, **kwargs):
        self.step("create")
        child = SimpleNamespace(
            show=lambda visible: self.step("show"),
            messageLoop=lambda: self.step("loop"),
            getResult=lambda: self.step("result") or self.result,
            result_saved=self.saved, commands_changed=True,
            draft=SimpleNamespace(name="saved"), edits=[],
            destroy=lambda: self.step("destroy"),
        )
        self.children.append(child)
        return child

    def popup(self):
        return self.namespace["popMenu"](self.parent, 40, 16, items=["item"])

    def editor(self):
        return self.namespace["open_editor"](
            self.parent, on_shown=lambda: self.step("shown"), on_saved=lambda: self.step("saved"),
        )

    def test_failure_at_each_stage_and_successful_reopen(self):
        for opener, stages in ((self.popup, ("create", "position", "show", "disable", "loop", "result")),
                               (self.editor, ("create", "disable", "shown", "loop"))):
            for stage in stages:
                with self.subTest(opener=opener.__name__, stage=stage):
                    self.setUp()
                    failure = RuntimeError(stage)
                    self.failures[stage] = failure
                    with self.assertRaises(RuntimeError) as caught:
                        opener()
                    self.assertIs(caught.exception, failure)
                    self.assertTrue(self.enabled)
                    if stage != "create":
                        self.assertEqual(self.events[-3:], ["enable", "activate", "destroy"])
                    self.failures.clear()
                    opener()
                    self.assertTrue(self.enabled)
                    self.assertEqual(self.events[-3:], ["enable", "activate", "destroy"])

    def test_cleanup_failures_keep_primary_and_attempt_every_step(self):
        for opener in (self.popup, self.editor):
            for primary in ("loop", "enable", "activate", "destroy"):
                with self.subTest(opener=opener.__name__, primary=primary):
                    self.setUp()
                    stages = ("loop", "enable", "activate", "destroy")
                    self.failures = {stage: RuntimeError(stage) for stage in stages[stages.index(primary):]}
                    with self.assertRaises(RuntimeError) as caught:
                        opener()
                    self.assertIs(caught.exception, self.failures[primary])
                    self.assertEqual(self.events[-3:], ["enable", "activate", "destroy"])
                    notes = getattr(caught.exception, "__notes__", [])
                    self.assertEqual(len(notes), len(self.failures) - 1)
                    self.assertTrue(all(stage in note for stage, note in zip(list(self.failures)[1:], notes)))

    def test_disabled_parent_stays_disabled_and_is_not_activated(self):
        for opener in (self.popup, self.editor):
            with self.subTest(opener=opener.__name__):
                self.setUp()
                self.enabled = False
                opener()
                self.assertFalse(self.enabled)
                self.assertNotIn("enable", self.events)
                self.assertNotIn("activate", self.events)
                self.assertEqual(self.events[-1], "destroy")

    def test_results_cancel_and_saved_callback_order(self):
        for result in (-1, 0, (1, 2)):
            self.result = result
            self.assertEqual(self.popup(), result)
        self.events.clear()
        self.saved = True
        self.assertEqual(self.editor(), "saved")
        self.assertEqual(self.events, ["create", "disable", "shown", "loop", "enable", "activate", "destroy", "saved"])
        self.failures["saved"] = RuntimeError("saved")
        with self.assertRaisesRegex(RuntimeError, "saved"):
            self.editor()
        self.assertTrue(self.enabled)
        self.assertEqual(self.events[-2:], ["destroy", "saved"])

    def test_nested_modal_restores_parent_only_after_outer_scope(self):
        outer = SimpleNamespace(destroy=lambda: self.step("outer-destroy"))
        with _modal_dialog_scope(self.parent, outer, self.parent.isEnabled()):
            self.parent.enable(False)
            self.editor()
            self.assertFalse(self.enabled)
            self.assertNotIn("activate", self.events)
        self.assertTrue(self.enabled)
        self.assertEqual(self.events, ["disable", "create", "disable", "shown", "loop",
                                      "destroy", "enable", "activate", "outer-destroy"])

    def test_parent_state_is_captured_before_child_construction(self):
        create = self.namespace["ListWindow"]
        def child(*args, **kwargs):
            self.enabled = False
            return create(*args, **kwargs)
        self.namespace["ListWindow"] = child
        self.popup()
        self.assertTrue(self.enabled)
        self.assertEqual(self.events[-3:], ["enable", "activate", "destroy"])

    def test_editor_destroy_attempts_all_edits_planes_and_native_window(self):
        tree = ast.parse((ROOT / "clnch/clnch_cmdeditor.py").read_text(encoding="utf-8"))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "CommandEditor")
        cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "destroy"]
        owner = self
        class Window:
            def destroy(self): owner.step("window")
        self.namespace["ckit"] = SimpleNamespace(TextWindow=Window)
        exec(compile(ast.Module(body=[cls], type_ignores=[]), "editor-destroy", "exec"), self.namespace)  # noqa: S102  # Execute real teardown with failing resources.
        editor = self.namespace["CommandEditor"]()
        editor.edits = [SimpleNamespace(destroy=lambda name=name: self.step(name)) for name in ("edit1", "edit2")]
        editor._row_planes = {name: SimpleNamespace(destroy=lambda name=name: self.step(name)) for name in ("plane1", "plane2")}
        expected = ["edit1", "edit2", "plane1", "plane2", "window"]
        self.failures = {name: RuntimeError(name) for name in expected}
        with self.assertRaises(RuntimeError) as caught:
            editor.destroy()
        self.assertIs(caught.exception, self.failures["edit1"])
        self.assertEqual(self.events, expected)
        self.assertEqual(len(caught.exception.__notes__), 4)

    def test_constructor_cleanup_runs_only_on_error(self):
        cleanup = self.namespace["_cleanup_on_exit"]
        with cleanup(self.step, "destroy", error_only=True):
            self.step("success")
        self.assertEqual(self.events, ["success"])
        with (
            self.assertRaisesRegex(RuntimeError, "construction"),
            cleanup(self.step, "destroy", error_only=True),
        ):
            raise RuntimeError("construction")
        self.assertEqual(self.events, ["success", "destroy"])

    def test_shutdown_exceptions_are_preserved_while_cleanup_continues(self):
        for primary in (KeyboardInterrupt(), SystemExit(1)):
            with self.subTest(exception=type(primary).__name__):
                self.failures = {"loop": primary, "enable": RuntimeError("enable")}
                with self.assertRaises(type(primary)) as caught:
                    self.popup()
                self.assertIs(caught.exception, primary)
                self.assertEqual(self.events[-3:], ["enable", "activate", "destroy"])

    def test_standard_editor_leaves_parent_visibility_unchanged(self):
        tree = ast.parse((ROOT / "clnch/clnch_standard.py").read_text(encoding="utf-8"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_open_command_editor")
        exec(compile(ast.Module(body=[method], type_ignores=[]), "standard-editor", "exec"), self.namespace)  # noqa: S102  # Exercise the actual entry without a native window.
        for visible in (False, True):
            for failed in (False, True):
                with self.subTest(visible=visible, failed=failed):
                    parent = SimpleNamespace(isVisible=lambda visible=visible: visible, show=lambda *a: self.fail("parent visibility changed"))
                    controller = SimpleNamespace(window=parent, reload_commands=lambda: None)
                    def open_editor(main, parent=parent, visible=visible, failed=failed, **options):
                        self.assertIs(main, parent)
                        self.assertEqual(main.isVisible(), visible)
                        if failed:
                            raise RuntimeError("open")
                        return "saved"
                    with patch.dict(sys.modules, {"clnch_cmdeditor": SimpleNamespace(open_editor=open_editor)}):
                        if failed:
                            with self.assertRaisesRegex(RuntimeError, "open"):
                                self.namespace["_open_command_editor"](controller)
                        else:
                            self.assertEqual(self.namespace["_open_command_editor"](controller), "saved")

    def test_font_cleanup_attempts_planes_fonts_and_dc_after_failures(self):
        tree = ast.parse((ROOT / "clnch/clnch_fontlistwindow.py").read_text(encoding="utf-8"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_clearPreviews")
        self.namespace["_gdi"] = SimpleNamespace(DeleteObject=lambda font: self.step(font), DeleteDC=lambda dc: self.step(dc))
        exec(compile(ast.Module(body=[method], type_ignores=[]), "font-cleanup", "exec"), self.namespace)  # noqa: S102  # Execute real teardown with failing native-resource doubles.
        preview = SimpleNamespace(
            _preview_dc="dc", _preview_fonts={"a": ("font1", 10), "b": ("font2", 10)},
            _preview_planes={name: SimpleNamespace(destroy=lambda name=name: self.step(name)) for name in ("plane1", "plane2")},
            _preview_images={"row": "image"},
        )
        expected = ["plane1", "plane2", "font1", "font2", "dc"]
        self.failures = {name: RuntimeError(name) for name in expected}
        with self.assertRaises(RuntimeError) as caught:
            self.namespace["_clearPreviews"](preview)
        self.assertIs(caught.exception, self.failures["plane1"])
        self.assertEqual(self.events, expected)
        self.assertEqual(len(caught.exception.__notes__), 4)
        self.assertEqual((preview._preview_planes, preview._preview_fonts, preview._preview_images, preview._preview_dc), ({}, {}, {}, None))

    def test_dialog_destroy_attempts_each_edit_and_base_after_failures(self):
        tree = ast.parse((ROOT / "ckit/ckit_dialog.py").read_text(encoding="utf-8"))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Dialog")
        cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "destroy"]
        owner = self
        class Window:
            def destroy(self): owner.step("window")
        class Edit:
            def __init__(self, name):
                self.widget = SimpleNamespace(destroy=lambda: owner.step(name))
        self.namespace.update(ckit_textwindow=SimpleNamespace(TextWindow=Window), _ExitStack=ExitStack)
        exec(compile(ast.Module(body=[cls], type_ignores=[]), "dialog-destroy", "exec"), self.namespace)  # noqa: S102  # Execute actual Dialog teardown with failing widgets.
        dialog_class = self.namespace["Dialog"]
        dialog_class.Edit = Edit
        dialog = dialog_class()
        dialog.items = [Edit("edit1"), object(), Edit("edit2")]
        expected = ["edit1", "edit2", "window"]
        self.failures = {name: RuntimeError(name) for name in expected}
        with self.assertRaises(RuntimeError) as caught:
            dialog.destroy()
        self.assertIs(caught.exception, self.failures["edit1"])
        self.assertEqual(self.events, expected)
        self.assertEqual(len(caught.exception.__notes__), 2)


if __name__ == "__main__":
    unittest.main()
