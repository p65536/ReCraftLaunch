"""Execute registered actions; registration and GUI rebuilding belong to callers."""
import os
from functools import partial

import clnch_misc
import clnch_strings as strings
from clnch_cmdstore import validate_link
from clnch_commandplatform import (
    _get_target_dir,
    get_mapped_directory,
    split_commandline_args,
    split_commandline_target,
)

import ckit
from ckit import MODKEY_CTRL, MODKEY_SHIFT
from pyauto import shellExecute


def argument_string(info):
    raw = getattr(info, "arg_string", None)
    return raw if raw is not None else clnch_misc.joinArgs(info.args)


def combine_arguments(fixed, incoming):
    """Insert raw input once, or append it without changing either fragment."""
    if "%param%" in fixed:
        return clnch_misc.replaceMacro(fixed, {"%%": "%%", "%param%": incoming}, environ=False)
    return fixed + " " + incoming if fixed and incoming else fixed or incoming


class ActionInfo:
    def __init__(self, args, workdir=None, shell_verb=None, view_mode=None, alias_path=(), arg_string=None):
        self.mod = 0
        self.args = args
        self.arg_string = arg_string
        self.workdir = workdir
        self.shell_verb = shell_verb
        self.view_mode = view_mode
        self._alias_path = alias_path


class CommandExecutor:
    def __init__(self, window, registry):
        self.window = window
        self.registry = registry

    def make_handler(self, name, target=None, on_ctrl=None, on_shift=None, on_ctrl_shift=None):
        return partial(self.execute, name, target, on_ctrl, on_shift, on_ctrl_shift)

    def execute(self, name, target, on_ctrl, on_shift, on_ctrl_shift, info):
        # Match info.mod exactly against the MODKEY_* combinations.
        mod = info.mod

        if mod == 0:
            self.run_action(target, info, name)
            return

        if mod == MODKEY_CTRL:
            modifier, action = "CTRL", on_ctrl
        elif mod == MODKEY_SHIFT:
            modifier, action = "SHIFT", on_shift
        elif mod == (MODKEY_CTRL | MODKEY_SHIFT):
            modifier, action = "CTRL_SHIFT", on_ctrl_shift
        else:
            return

        if action:
            self.run_action(action, info, name)
            return

        self.run_default(name, target, modifier, info)

    def run_default(self, name, target, modifier, info):
        # Read current settings so menu changes do not require rebuilding commands or custom hooks.
        settings = self.window.modifier_settings
        default_action = settings[modifier + "_ACTION"]
        if default_action == "execute":
            self.run_action(
                target,
                ActionInfo(
                    info.args,
                    workdir=getattr(info, "workdir", None),
                    shell_verb=getattr(info, "shell_verb", None),
                    view_mode=getattr(info, "view_mode", None),
                    alias_path=getattr(info, "_alias_path", ()),
                    arg_string=getattr(info, "arg_string", None),
                ),
                name,
            )
        elif default_action in ("target_folder", "mapped_folder"):
            real_path = self.registry.resolve_path(name)
            if not real_path:
                return
            inherited_workdir, alias_arguments = self.registry.resolve_context(name)
            raw = argument_string(info)
            for fixed in alias_arguments:
                raw = combine_arguments(fixed, raw)
            args = split_commandline_args(raw)
            macros = {"%%": "%", "%param%": " ".join(args)}
            real_path = clnch_misc.replaceMacro(real_path, macros, environ=True)
            validate_link(real_path, name)
            workdir = clnch_misc.replaceMacro(
                getattr(info, "workdir", None) or inherited_workdir, macros, environ=True,
            )
            if default_action == "mapped_folder":
                source_roots = tuple(settings["SOURCE_ROOTS"])
                destination_root = settings[modifier + "_DESTINATION_ROOT"]

            def jobOpenFolder(job_item):
                # Keep filesystem/OS lookup and Shell waits off the UI thread.
                try:
                    if default_action == "target_folder":
                        directory = _get_target_dir(real_path, workdir)
                    else:
                        directory = get_mapped_directory(real_path, source_roots, destination_root, workdir)
                    if directory and os.path.isdir(directory):
                        shellExecute(None, directory, "", "")
                except Exception as e:  # noqa: BLE001  # Match ShellExecuteCommand's launch-failure notification.
                    print(strings.EXECUTE_ERROR)
                    print("  %s" % str(e))  # noqa: UP031  # Match the existing launch-error format.

            job_item = ckit.JobItem(jobOpenFolder, None)
            clnch_misc._require_job_queue(ckit.JobQueue.defaultQueue()).enqueue(job_item)

    def run_action(self, act, info, name):
        if not act:
            return

        if callable(act):
            act(info)
            return

        cmd_or_path = act["link"].strip()
        if not cmd_or_path:
            return
        fixed_args = act.get("args", "")
        alias_path = getattr(info, "_alias_path", ())
        step = (name.lower(), info.mod, cmd_or_path.lower(), fixed_args, len(info.args))
        # _ra can revisit a command while consuming a finite argument list.
        if any(previous[:-1] == step[:-1] and previous[-1] <= step[-1]
               for previous in alias_path):
            path = " → ".join(item[0] or "''" for item in (*alias_path, step))
            raise ValueError(strings.COMMAND_ALIAS_CYCLE.format(path=path))
        alias_path = (*alias_path, step)
        act_workdir = getattr(info, "workdir", None) or act.get("workdir", "")
        # Preserve the view mode supplied by the caller; otherwise use this action's mode.
        view_mode = getattr(info, "view_mode", None) or act.get("view_mode")

        # Look up registered commands before treating the link as a path.
        matched_handler = self.registry.get_handler(cmd_or_path)

        # Execute the referenced command if one is registered.
        if matched_handler:
            combined = combine_arguments(fixed_args, argument_string(info))
            child_args = split_commandline_args(combined)

            matched_handler(
                ActionInfo(
                    child_args,
                    workdir=act_workdir,
                    shell_verb=getattr(info, "shell_verb", None),
                    view_mode=view_mode,
                    alias_path=alias_path,
                    arg_string=combined,
                )
            )

        else:
            self.run_shell(cmd_or_path, fixed_args, act_workdir, view_mode, info, alias_path[0][0])

    def run_shell(self, cmd_or_path, fixed_args, act_workdir, view_mode, info, name):
        # Use ShellExecuteCommand inherited from CraftLaunch.
        # ShellExecuteCommand defaults an empty param to %param%.
        # Append dynamic arguments (%param%) unless the fixed arguments already contain the placeholder.
        if fixed_args:
            param = (
                fixed_args if "%param%" in fixed_args or not argument_string(info) else (fixed_args + " %param%")
            )
        else:
            param = ""

        command = self.window.ShellExecuteCommand(
            getattr(info, "shell_verb", None),
            cmd_or_path,
            param,
            act_workdir,
            view_mode,
            _command_name=name,
        )
        command(info)

    def elevate(self, info):
        if not argument_string(info):
            return

        link, args = split_commandline_target(argument_string(info))
        if not link:
            return
        elevated_info = ActionInfo(
            split_commandline_args(args),
            workdir=getattr(info, "workdir", None),
            shell_verb="runas",
            view_mode=getattr(info, "view_mode", None),
            alias_path=getattr(info, "_alias_path", ()),
            arg_string=args,
        )
        self.run_action(
            {"link": link},
            elevated_info,
            "_ra",
        )
