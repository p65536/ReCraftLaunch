import ast
import configparser
import io
import json
import math

import clnch_strings as strings

import pyauto

# -------------------------------------------------------------------------


class IpcData:
    options = [  # noqa: RUF012  # Shared IPC option specification.
        "execute=",
        "text=",
        "selection=",
        "position=",
    ]

    def __init__(self, data=None):
        self.ini = configparser.RawConfigParser()
        self.num_execute = 0

        if data:
            fd = io.StringIO(data)
            self.ini.read_file(fd)
            self.num_execute = self._countOption("EXECUTE", "item")

    def getValue(self):
        fd = io.StringIO("")
        self.ini.write(fd)
        return fd.getvalue().strip()

    def trySetOption(self, option, value):
        # JSON quoting protects input whitespace from ConfigParser's value trimming.
        if option == "--execute":
            self._addSection("EXECUTE")
            self.ini.set("EXECUTE", f"item{self.num_execute}", json.dumps(value, ensure_ascii=False))
            self.num_execute += 1
            return True

        elif option == "--text":
            self._addSection("COMMANDLINE")
            self.ini.set("COMMANDLINE", "text", json.dumps(value, ensure_ascii=False))
            return True

        elif option == "--selection":
            self._addSection("COMMANDLINE")
            self.ini.set("COMMANDLINE", "selection", value)
            return True

        elif option == "--position":
            self._addSection("COMMANDLINE")
            self.ini.set("COMMANDLINE", "position", value)
            return True

        return False

    def _addSection(self, section):
        try:
            self.ini.add_section(section)
        except configparser.DuplicateSectionError:
            pass

    def _countOption(self, section, option):
        count = 0
        while True:
            try:
                self.ini.get(section, f"{option}{count}")
            except (configparser.NoOptionError, configparser.NoSectionError):
                break
            count += 1
        return count

    def _getOptionList(self, section, option):
        items = []
        count = 0
        while True:
            try:
                items.append(json.loads(self.ini.get(section, f"{option}{count}")))
            except (configparser.NoOptionError, configparser.NoSectionError):
                break
            count += 1
        return items

    def getExecuteList(self):
        return self._getOptionList("EXECUTE", "item")

    def execute(self, main_window):
        class CommandLine:
            def __init__(self):
                self.planned_command_list = []

            def planCommand(self, command, info, history):
                self.planned_command_list.append((command, info))

            def setText(self, text):
                pass

            def selectAll(self):
                pass

            def appendHistory(self, newentry):
                pass

            def quit(self):
                pass

        for text in self._getOptionList("EXECUTE", "item"):
            commandline = CommandLine()
            for commandline_function in main_window.commandline_list:
                if commandline_function.onEnter(commandline, text, 0):
                    break
            for command, info in commandline.planned_command_list:
                try:
                    command(info)
                except Exception as e:  # noqa: BLE001  # Report command failures as in interactive execution.
                    print(e)

    def commandLine(self, main_window):
        text = None
        selection = None
        str_position = None
        position = None

        try:
            text = json.loads(self.ini.get("COMMANDLINE", "text"))
        except (configparser.NoOptionError, configparser.NoSectionError):
            pass

        try:
            selection = self.ini.get("COMMANDLINE", "selection")
        except (configparser.NoOptionError, configparser.NoSectionError):
            pass

        try:
            str_position = self.ini.get("COMMANDLINE", "position")
        except (configparser.NoOptionError, configparser.NoSectionError):
            pass

        if str_position is not None:
            try:
                position = ast.literal_eval(str_position)
                if (not isinstance(position, (tuple, list)) or len(position) != 2
                        or any(type(value) not in (int, float) or not math.isfinite(value)
                               for value in position)):
                    raise ValueError("Expected two finite numeric coordinates")
                position_x_ratio = position[0] / 100.0
                position_y_ratio = position[1] / 100.0
            except Exception:  # noqa: BLE001  # Report invalid position literals and numeric conversion failures.
                print(strings.IPC_POSITION_ERROR.format(position=str_position))
                return

        if not text and not selection and not position:
            return

        # Return to the modal child without re-entering the main input loop.
        if not main_window.isEnabled():
            main_window.foreground()
            return

        if text is None:
            text = ""

        # Determine the selection range.
        command_len = text.find(";")
        if command_len < 0:
            command_len = len(text)
        argument_begin = min(command_len + 1, len(text))

        if selection is None:
            selection = "5"

        if selection == "0":
            selection = [0, 0]
        elif selection == "1":
            selection = [0, command_len]
        elif selection == "2":
            selection = [command_len, command_len]
        elif selection == "3":
            selection = [argument_begin, argument_begin]
        elif selection == "4":
            selection = [argument_begin, len(text)]
        elif selection == "5":
            selection = [len(text), len(text)]
        elif selection == "A":
            selection = [0, len(text)]
        else:
            print(strings.IPC_SELECTION_ERROR.format(selection=selection))
            selection = [0, 0]

        # Move the window.
        if position is not None:
            clnch_wnd = pyauto.Window.fromHWND(main_window.getHWND())
            clnch_rect = clnch_wnd.getRect()

            fg_wnd = pyauto.Window.getForeground()
            if fg_wnd is not None:
                fg_rect = fg_wnd.getRect()

                x = (
                    fg_rect[0]
                    + ((fg_rect[2] - fg_rect[0]) - (clnch_rect[2] - clnch_rect[0]))
                    * position_x_ratio
                )
                y = (
                    fg_rect[1]
                    + ((fg_rect[3] - fg_rect[1]) - (clnch_rect[3] - clnch_rect[1]))
                    * position_y_ratio
                )

                main_window.setPosSize(
                    int(x), int(y), main_window.width(), main_window.height(), 0
                )

        # Activate the main window.
        main_window.restore()
        main_window.foreground()
        main_window.activate()

        # Run the local message loop.
        main_window.activeMessageLoop(text=text, selection=selection)

        # Restore the saved position.
        main_window.resetPos()


# -------------------------------------------------------------------------
