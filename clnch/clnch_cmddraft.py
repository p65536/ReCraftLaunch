"""Command editing state and edit-specific validation, independent of the GUI/I/O."""
import copy

from clnch_cmdstore import MODIFIERS, is_valid_command_name


class DraftValidationError(ValueError):
    def __init__(self, code, modifier=None):
        super().__init__(code)
        self.code = code
        self.modifier = modifier


class CommandDraft:
    """Edit a validated store snapshot without mutating it or completing defaults."""

    def __init__(self, commands, target_cmd=None):
        self.original_commands = copy.deepcopy(commands)
        self.target_name = target_cmd.lower() if target_cmd is not None else None
        self.name = self.target_name or ""
        self.modifier_index = 0
        self._actions = copy.deepcopy(commands.get(self.target_name, {})) if self.is_edit_mode else {}

    @property
    def is_edit_mode(self):
        return self.target_name is not None

    @property
    def empty_command(self):
        return self.target_name == ""

    @property
    def current_action(self):
        return self._actions.get(MODIFIERS[self.modifier_index], {}).copy()

    def update_current(self, name, action):
        self.name = "" if self.empty_command else name.lower()
        self._actions[MODIFIERS[self.modifier_index]] = {
            **{field: action[field].strip() for field in ("link", "workdir")},
            "args": action["args"],
            "view_mode": action["view_mode"],
        }

    def switch_modifier(self, index):
        self.modifier_index = index
        return self.current_action

    def build_commands(self):
        """Validate edits and return a save candidate; the store normalizes/writes it."""
        if not is_valid_command_name(self.name):
            raise DraftValidationError("invalid_name")
        if self.name in self.original_commands and self.name != self.target_name:
            raise DraftValidationError("duplicate")
        entry = {}
        for modifier, action in self._actions.items():
            if action.get("link", "").strip():
                entry[modifier] = action.copy()
            elif (
                action.get("args") or action.get("workdir")
                or action.get("view_mode", "normal") != "normal"
            ):
                raise DraftValidationError("modifier_link_required", modifier)
        if not entry and not self.name:
            raise DraftValidationError("link_required")

        commands = copy.deepcopy(self.original_commands)
        if self.target_name != self.name:
            commands.pop(self.target_name, None)
        commands[self.name] = entry
        return commands
