"""Own standard/JSON registrations while keeping the public command list editable."""

from clnch_cmdstore import normalize_action

_NO_TARGET = object()


class _RegisteredCommand(tuple):
    """A (name, handler) pair with explicit ownership and unresolved target."""

    owner: "CommandRegistry"
    source: str
    target: object

    def __new__(cls, owner, name, handler, source, target=_NO_TARGET):
        item = super().__new__(cls, (name, handler))
        item.owner = owner
        item.source = source
        item.target = target
        return item


class CommandRegistry:
    def __init__(self, commands):
        self._standard = {
            name.lower(): _RegisteredCommand(self, name, handler, "standard")
            for name, handler in commands
        }
        self._json = {}

    def register(self, name, handler, target=None):
        self._standard[name.lower()] = _RegisteredCommand(
            self, name, handler, "standard", target
        )

    def _find(self, name):
        key = name.lower()
        return self._json.get(key, self._standard.get(key))

    def get_handler(self, name):
        item = self._find(name)
        return item[1] if item is not None else None

    def resolve_path(self, name):
        # Return the terminal Link string, without OS lookup, expansion or existence checks (F12).
        item = self._find(name)
        if item is None or item.target is _NO_TARGET:
            return None
        return self._resolve_target(item.target, set())

    def resolve_context(self, name):
        # Match execution's WorkDir inheritance and prepended alias argument strings.
        # Return argument fragments in traversal order, ready to apply to incoming arguments.
        visited = set()
        workdir, arguments = "", []
        while name.lower() not in visited:
            visited.add(name.lower())
            item = self._find(name)
            if item is None or not isinstance(item.target, dict):
                break
            if not workdir:
                workdir = item.target.get("workdir", "")
            name = item.target["link"].strip()
            if self._find(name) is None:
                break
            arguments.append(item.target.get("args", ""))
        return workdir, arguments

    def _resolve_target(self, target, visited):
        if not target:
            return None
        if isinstance(target, dict):
            target = target["link"]
        if not isinstance(target, str) or not target.strip():
            return None
        path = target.strip()
        key = path.lower()
        item = self._find(key)
        if item is None or item.target is _NO_TARGET:
            return path
        if key in visited:
            return None
        visited.add(key)
        return self._resolve_target(item.target, visited)

    def rebuild(self, launcher, commands, make_handler, *, preserve_custom=True):
        # Prepare the whole replacement before changing live handlers or targets.
        json_commands = {}
        for name, params in commands.items():
            actions = {modifier: normalize_action(action)
                       for modifier, action in params.items()}
            json_commands[name.lower()] = _RegisteredCommand(
                self, name, make_handler(name, **actions), "json", actions.get("target")
            )
        combined = {**self._standard, **json_commands}
        command_list = []
        insert_at = None
        if preserve_custom:
            for item in launcher.command_list:
                if isinstance(item, _RegisteredCommand) and item.owner is self:
                    replacement = combined.pop(item[0].lower(), None)
                    if replacement is not None:
                        command_list.append(replacement)
                    # Even a deleted slot anchors additions before trailing custom entries.
                    insert_at = len(command_list)
                else:
                    command_list.append(item)
        if insert_at is None:
            insert_at = len(command_list)
        command_list[insert_at:insert_at] = combined.values()
        self._json = json_commands
        launcher.command_list = command_list
