"""Registration, lazy resolution and rebuilding without GUI or Windows imports."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "clnch"))
from clnch_commandregistry import CommandRegistry


class CommandRegistryTests(unittest.TestCase):
    def setUp(self):
        self.first, self.last = Mock(), Mock()
        self.registry = CommandRegistry([("Builtin", self.first), ("BUILTIN", self.last)])
        self.launcher = SimpleNamespace(command_list=[])
        self.factory = Mock(side_effect=lambda name, **actions: Mock())

    def rebuild(self, commands):
        self.registry.rebuild(self.launcher, commands, self.factory)

    def test_standard_duplicates_and_json_override_restore_handler_and_target(self):
        self.assertIs(self.registry.get_handler("builtin"), self.last)
        self.registry.register("Tool", self.first, {"link": "first.exe"})
        self.registry.register("TOOL", self.last, {"link": "last.exe"})
        self.rebuild({"tool": {"target": {"link": "json.exe"}}, "later": {}})
        self.assertEqual([item[0] for item in self.launcher.command_list], ["BUILTIN", "tool", "later"])
        self.assertEqual(self.registry.resolve_path("TOOL"), "json.exe")
        self.rebuild({})
        self.assertIs(self.registry.get_handler("tool"), self.last)
        self.assertEqual(self.registry.resolve_path("tool"), "last.exe")
        self.assertEqual([item[0] for item in self.launcher.command_list], ["BUILTIN", "TOOL"])

    def test_alias_resolution_is_lazy_case_insensitive_and_cycle_safe(self):
        self.registry.register("alias", self.first, {"link": " CHILD "})
        self.registry.register("child", self.last, {"link": " tool.exe "})
        self.assertEqual(self.registry.resolve_path("ALIAS"), "tool.exe")
        self.rebuild({"child": {"target": {"link": "alias"}}})
        self.assertIsNone(self.registry.resolve_path("alias"))
        self.rebuild({})
        self.assertEqual(self.registry.resolve_path("alias"), "tool.exe")

    def test_builtin_reference_and_non_path_targets_keep_existing_resolution(self):
        self.registry.register("alias", self.first, {"link": " Builtin "})
        self.assertEqual(self.registry.resolve_path("alias"), "Builtin")
        self.assertIsNone(self.registry.resolve_path("builtin"))
        self.assertIsNone(self.registry.resolve_path("missing"))
        for target in (None, self.first, {"link": ""}):
            self.registry.register("no_path", self.first, target)
            self.assertIsNone(self.registry.resolve_path("no_path"))

    def test_workdir_uses_first_nonempty_alias_value_and_stops_on_cycles(self):
        self.rebuild({"outer": {"target": {"link": "middle", "workdir": "parent", "args": "--outer"}},
                      "middle": {"target": {"link": "child", "args": "--inner"}},
                      "child": {"target": {"link": "tool.exe", "workdir": "child"}},
                      "cycle": {"target": {"link": "cycle"}}})
        self.assertEqual(self.registry.resolve_context("OUTER"), ("parent", ["--outer", "--inner"]))
        self.assertEqual(self.registry.resolve_context("middle"), ("child", ["--inner"]))
        for name in ("cycle", "builtin", "missing"):
            self.assertEqual(self.registry.resolve_context(name)[0], "")

    def test_owned_pairs_are_tuple_compatible_and_custom_entries_keep_order(self):
        self.rebuild({"json": {}})
        standard, generated = self.launcher.command_list
        self.assertIsInstance(generated, tuple)
        self.assertEqual(len(generated), 2)
        self.assertEqual(generated.source, "json")
        self.assertEqual(standard.source, "standard")
        self.assertIs(generated.owner, self.registry)
        custom = ("JSON", self.first)
        wrapped = (generated[0], generated[1])
        edited = ["edited", self.last]
        # Direct insertion, list replacement, tuple recreation and deletion are supported.
        self.launcher.command_list = [custom, generated, wrapped, edited]
        for _ in range(2):
            self.rebuild({"json": {}})
            self.assertEqual(self.launcher.command_list,
                             [custom, self.registry._json["json"], standard, wrapped, edited])
            self.assertIs(self.launcher.command_list[0], custom)
            self.assertEqual(len(self.launcher.command_list), 5)
        self.launcher.command_list.remove(custom)
        self.rebuild({})
        self.assertEqual(self.launcher.command_list, [standard, wrapped, edited])

    def test_another_registrys_entries_are_not_owned(self):
        other = CommandRegistry([("other", self.first)])
        other.rebuild(self.launcher, {}, self.factory)
        external = self.launcher.command_list[0]
        self.rebuild({})
        self.assertIs(self.launcher.command_list[0], external)

    def test_custom_positions_survive_updates_additions_deletions_and_repeated_saves(self):
        self.rebuild({"first": {}, "last": {}})
        builtin, first, last = self.launcher.command_list
        head, middle, tail = [(name, Mock()) for name in ("head", "middle", "tail")]
        self.launcher.command_list = [head, builtin, first, middle, last, tail]
        for _ in range(3):
            previous = self.launcher.command_list.copy()
            self.rebuild({"added": {}, "last": {"target": {"link": "new.exe"}}, "first": {}})
            self.assertEqual([item[0] for item in self.launcher.command_list],
                             ["head", "BUILTIN", "first", "middle", "last", "added", "tail"])
            self.assertIs(self.launcher.command_list[0], head)
            self.assertIs(self.launcher.command_list[3], middle)
            self.assertIs(self.launcher.command_list[-1], tail)
            for item in previous:
                if getattr(item, "source", None) == "json":
                    self.assertFalse(any(current is item for current in self.launcher.command_list))
            self.assertEqual(self.registry.resolve_path("last"), "new.exe")
        self.rebuild({"last": {}})
        self.assertEqual([item[0] for item in self.launcher.command_list],
                         ["head", "BUILTIN", "middle", "last", "tail"])
        self.rebuild({})
        self.assertEqual(self.launcher.command_list, [head, builtin, middle, tail])

    def test_same_name_custom_entries_keep_priority_when_json_overrides_builtin(self):
        self.rebuild({})
        head, tail = ("builtin", Mock()), ("Builtin", Mock())
        self.launcher.command_list.insert(0, head)
        self.launcher.command_list.append(tail)
        for commands in ({"builtin": {}}, {"BUILTIN": {"target": {"link": "new.exe"}}}, {}):
            self.rebuild(commands)
            self.assertEqual(len(self.launcher.command_list), 3)
            self.assertIs(self.launcher.command_list[0], head)
            self.assertIs(self.launcher.command_list[-1], tail)
            self.assertIs(self.launcher.command_list[1][1], self.registry.get_handler("builtin"))

    def test_deleted_last_managed_slot_anchors_new_names_before_trailing_custom(self):
        self.registry = CommandRegistry([])
        self.rebuild({"old": {}})
        head, tail = ("head", Mock()), ("tail", Mock())
        self.launcher.command_list.insert(0, head)
        self.launcher.command_list.append(tail)
        self.rebuild({"new": {}})
        self.assertEqual([item[0] for item in self.launcher.command_list], ["head", "new", "tail"])
        self.rebuild({})
        self.assertEqual(self.launcher.command_list, [head, tail])
        self.rebuild({"later": {}})
        self.assertEqual([item[0] for item in self.launcher.command_list], ["head", "tail", "later"])

    def test_repeated_owned_entries_are_replaced_once_but_equal_plain_pairs_are_kept(self):
        self.rebuild({"json": {}})
        builtin, generated = self.launcher.command_list
        plain = tuple(generated)
        self.launcher.command_list = [generated, plain, builtin, generated]
        self.rebuild({"json": {}})
        self.assertEqual([item[0] for item in self.launcher.command_list], ["json", "json", "BUILTIN"])
        self.assertIs(self.launcher.command_list[1], plain)

    def test_factory_failure_preserves_list_handlers_and_alias_resolution(self):
        self.rebuild({"old": {"target": {"link": "old.exe"}}})
        before = self.launcher.command_list
        handler = self.registry.get_handler("old")
        self.factory.side_effect = [Mock(), RuntimeError("compile failed")]
        with self.assertRaisesRegex(RuntimeError, "compile failed"):
            self.rebuild({"first": {}, "second": {}})
        self.assertIs(self.launcher.command_list, before)
        self.assertIs(self.registry.get_handler("old"), handler)
        self.assertEqual(self.registry.resolve_path("old"), "old.exe")
        self.assertIsNone(self.registry.get_handler("first"))

    def test_sparse_actions_use_store_defaults_without_mutating_input(self):
        commands = {"tool": {"on_ctrl": {"link": "tool.exe"}}}
        self.rebuild(commands)
        self.factory.assert_called_once_with("tool", on_ctrl={
            "link": "tool.exe", "args": "", "workdir": "", "view_mode": "normal"})
        self.assertEqual(commands, {"tool": {"on_ctrl": {"link": "tool.exe"}}})
        self.assertIsNone(self.registry.resolve_path("tool"))

    def test_initial_application_discards_previous_external_entries(self):
        self.launcher.command_list = [("old_custom", self.first)]
        self.registry.rebuild(self.launcher, {}, self.factory, preserve_custom=False)
        self.assertEqual(self.launcher.command_list, [("BUILTIN", self.last)])


if __name__ == "__main__":
    unittest.main()
