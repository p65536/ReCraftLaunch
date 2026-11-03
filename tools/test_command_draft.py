"""Edit rules and state transitions without native modules or GUI widgets; run with -B."""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "clnch"))

from clnch_cmddraft import CommandDraft, DraftValidationError
from clnch_cmdstore import MODIFIERS, VIEW_MODES, normalize_action


class CommandDraftTests(unittest.TestCase):
    def update(self, draft, name=None, **values):
        draft.update_current(draft.name if name is None else name,
                             normalize_action({"link": "", **draft.current_action, **values}))

    def error(self, draft, code, modifier=None):
        with self.assertRaises(DraftValidationError) as raised:
            draft.build_commands()
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(raised.exception.modifier, modifier)

    def test_new_draft_does_not_inherit_empty_command(self):
        commands = {"": {key: {"link": key} for key in MODIFIERS}}
        draft = CommandDraft(commands)
        self.assertFalse(draft.is_edit_mode)
        self.assertFalse(draft.empty_command)
        self.assertIsNone(draft.target_name)
        self.assertEqual(draft.name, "")
        for index in range(4):
            self.assertEqual(draft.switch_modifier(index), {})
            self.update(draft, "NEW")
        self.assertEqual(draft.name, "new")
        self.assertEqual(draft.build_commands(), {**commands, "new": {}})

    def test_edit_loads_sparse_actions_and_lowercase_target(self):
        commands = {"tool": {"target": {"link": "tool.exe"},
                             "on_shift": {"link": "other.exe", "view_mode": "maximized"}}}
        draft = CommandDraft(commands, "TOOL")
        self.assertTrue(draft.is_edit_mode)
        self.assertEqual(draft.name, "tool")
        self.assertEqual(draft.modifier_index, 0)
        self.assertEqual(draft.current_action, {"link": "tool.exe"})
        self.assertEqual(draft.switch_modifier(1), {})
        self.assertEqual(draft.switch_modifier(2), commands["tool"]["on_shift"])
        self.assertEqual(draft.build_commands(), commands)

    def test_modifier_round_trip_keeps_all_fields_and_trims_only_edited_values(self):
        draft = CommandDraft({})
        actions = []
        for index in range(4):
            draft.switch_modifier(index)
            action = {"link": f"tool{index}.exe", "args": f"--arg {index}",
                      "workdir": f"D:/Work {index}", "view_mode": VIEW_MODES[index % 3]}
            draft.update_current("NAME", {key: " " + value + " " if key != "view_mode" else value
                                           for key, value in action.items()})
            actions.append({**action, "args": " " + action["args"] + " "})
        for index in (0, 3, 1, 2, 0):
            self.assertEqual(draft.switch_modifier(index), actions[index])
        self.assertEqual(draft.build_commands(), {"name": dict(zip(MODIFIERS, actions))})

    def test_unvisited_actions_keep_sparse_fields_and_whitespace(self):
        commands = {"tool": {"on_ctrl": {"link": " ctrl.exe ", "args": " spaced "},
                             "on_shift": {"link": "shift.exe", "workdir": " work "}}}
        draft = CommandDraft(commands, "tool")
        self.update(draft, link="target.exe")
        result = draft.build_commands()["tool"]
        self.assertEqual(result["on_ctrl"], commands["tool"]["on_ctrl"])
        self.assertEqual(result["on_shift"], commands["tool"]["on_shift"])
        self.assertNotIn("on_ctrl_shift", result)

    def test_visiting_absent_modifiers_does_not_register_them(self):
        draft = CommandDraft({"tool": {"target": {"link": "tool.exe"}}}, "tool")
        for index in range(4):
            draft.switch_modifier(index)
            self.update(draft)
        self.assertEqual(set(draft.build_commands()["tool"]), {"target"})

    def test_clearing_registered_modifier_removes_it(self):
        draft = CommandDraft({"tool": {"target": {"link": "tool.exe"},
                                       "on_ctrl": {"link": "ctrl.exe", "args": "--arg"}}}, "tool")
        draft.switch_modifier(1)
        self.update(draft, link="", args="")
        self.assertEqual(draft.build_commands(), {"tool": {"target": {"link": "tool.exe"}}})

    def test_link_is_required_for_partial_action_on_each_modifier(self):
        for index, modifier in enumerate(MODIFIERS):
            for values in ({"args": "--arg"}, {"workdir": "D:/Work"},
                           {"view_mode": "minimized"}, {"view_mode": "maximized"}):
                with self.subTest(modifier=modifier, values=values):
                    draft = CommandDraft({})
                    draft.switch_modifier(index)
                    self.update(draft, "name", link="  ", **values)
                    self.error(draft, "modifier_link_required", modifier)
                    self.update(draft, link="tool.exe")
                    self.assertEqual(draft.build_commands()["name"][modifier],
                                     normalize_action({"link": "tool.exe", **values}))

    def test_duplicate_name_precedes_action_validation_and_does_not_remove_source(self):
        commands = {"a": {"target": {"link": "a.exe"}}, "b": {}, "": {}}
        for target, name in (("a", "B"), ("a", ""), (None, "b"), (None, "")):
            with self.subTest(target=target, name=name):
                draft = CommandDraft(commands, target)
                self.update(draft, name, link="", args="--unfinished")
                self.error(draft, "duplicate")
                self.assertEqual(draft.original_commands, commands)

    def test_rename_replaces_old_key_but_keeps_snapshot_and_other_commands(self):
        commands = {"old": {"target": {"link": "old.exe"}}, "other": {}}
        draft = CommandDraft(commands, "OLD")
        self.update(draft, "New", link="new.exe")
        result = draft.build_commands()
        self.assertEqual(set(result), {"new", "other"})
        self.assertEqual(result["new"]["target"]["link"], "new.exe")
        self.assertEqual(draft.original_commands, commands)
        self.assertEqual(draft.build_commands(), result)
        self.update(draft, "OLD")
        self.assertEqual(set(draft.build_commands()), {"old", "other"})

    def test_invalid_name_blocks_new_and_rename_before_changing_snapshot(self):
        commands = {"old": {"target": {"link": "old.exe"}}, "other": {}}
        for target in (None, "old"):
            for name in (";", "a;b", "a;", ";b", '"a;b"') + (" foo", "foo ", " foo ", "foo bar", "foo \u00a0bar",
                    "foo\tbar", "foo\nbar", "foo\u3000bar", " \u00a0 "):
                with self.subTest(target=target, name=name):
                    draft = CommandDraft(commands, target)
                    self.update(draft, name, link="")
                    self.error(draft, "invalid_name")
                    self.assertEqual(draft.name, name.lower())
                    self.assertEqual(draft.original_commands, commands)
                    self.update(draft, "valid")
                    self.assertEqual(draft.build_commands()["valid"], {})

    def test_case_only_rename_and_missing_edit_target(self):
        for commands in ({"name": {}}, {}):
            with self.subTest(commands=commands):
                draft = CommandDraft(commands, "NAME")
                self.update(draft, "Name")
                self.assertEqual(draft.build_commands(), {"name": {}})

    def test_empty_command_locks_name_and_requires_at_least_one_action(self):
        for commands in ({}, {"": {}}):
            with self.subTest(commands=commands):
                draft = CommandDraft(commands, "")
                self.assertTrue(draft.is_edit_mode)
                self.assertTrue(draft.empty_command)
                self.update(draft, "ignored")
                self.assertEqual(draft.name, "")
                self.error(draft, "link_required")
                draft.switch_modifier(2)
                self.update(draft, "ignored", link="shift.exe")
                self.assertEqual(draft.build_commands(), {"": {"on_shift": normalize_action({"link": "shift.exe"})}})

    def test_new_empty_command_requires_action_but_named_empty_entry_is_allowed(self):
        draft = CommandDraft({})
        self.update(draft)
        self.error(draft, "link_required")
        self.update(draft, link="empty.exe")
        self.assertEqual(set(draft.build_commands()), {""})
        self.update(draft, "named", link="")
        self.assertEqual(draft.build_commands(), {"named": {}})

    def test_snapshots_display_values_and_save_candidates_are_independent(self):
        commands = {"tool": {"target": {"link": "tool.exe"}}, "other": {"target": {"link": "other.exe"}}}
        original = copy.deepcopy(commands)
        draft = CommandDraft(commands, "tool")
        values = draft.current_action
        values["link"] = "display-only"
        self.assertEqual(draft.current_action, original["tool"]["target"])
        commands["tool"]["target"]["link"] = "external"
        self.update(draft, "renamed", link="changed.exe")
        result = draft.build_commands()
        result["renamed"]["target"]["link"] = "candidate-only"
        result["other"]["target"]["link"] = "candidate-only"
        self.assertEqual(draft.current_action["link"], "changed.exe")
        self.assertEqual(draft.original_commands, original)


if __name__ == "__main__":
    unittest.main()
