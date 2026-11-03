import os
import sys
from copy import deepcopy

import clnch_altenterconfig
import clnch_execonfig
import clnch_ini
import clnch_inisettings as ini_settings
import clnch_inputconfig
import clnch_listwindow
import clnch_misc
import clnch_modifierconfig
import clnch_msgbox
import clnch_strings as strings

import ckit
import pyauto
from ckit.ckit_const import (
    MODKEY_CTRL,
    ORIGIN_X_CENTER,
    ORIGIN_Y_CENTER,
    VK_DELETE,
    VK_DOWN,
    VK_ESCAPE,
    VK_INSERT,
    VK_RETURN,
    VK_UP,
)
from ckit.ckit_misc import _cleanup_on_exit

# Config lists use the work-area limit in ListWindow instead of a fixed cell cap.

# --------------------------------------------------------------------


def _selectConfigValue(main_window, title, choices, current):
    """Return the selected value, or None on cancel; unknown values start at zero."""
    values = [item[1] if isinstance(item, tuple) else item for item in choices]
    initial = next((i for i, value in enumerate(values) if value == current), 0)
    result = clnch_listwindow.popMenu(
        main_window, sys.maxsize, 16, title, choices, initial
    )
    result, _result_mod = clnch_listwindow._split_list_result(result)
    return values[result] if result >= 0 else None


def _settingItem(title, value, action):
    return (strings.SETTING_VALUE.format(title=title, value=value), action)


def _iterConfigMenu(main_window, title, build_items, **menu_options):
    """Yield each selection, rebuilding labels and retaining the row on return."""
    select = 0
    while True:
        items = build_items()
        select = clnch_listwindow.popMenu(
            main_window, sys.maxsize, 16, title, items,
            min(select, len(items) - 1), **menu_options,
        )
        select, _result_mod = clnch_listwindow._split_list_result(select)
        if select < 0:
            return
        yield items, select


def _configTheme(main_window):
    def enumThemes():
        theme_list = []
        theme_parent = os.path.join(ckit.getAppExePath(), "themes")
        try:
            theme_file_list = os.listdir(theme_parent)
        except FileNotFoundError:
            return theme_list

        for theme_file in theme_file_list:
            name, ext = os.path.splitext(theme_file)
            if ext.lower() == ".ini" and os.path.isfile(
                os.path.join(theme_parent, theme_file)
            ):
                theme_list.append(name)

        return theme_list

    theme_list = enumThemes()
    if not theme_list:
        return

    current_theme_name = ini_settings.THEME_NAME.get(clnch_ini)

    try:
        initial_select = theme_list.index(current_theme_name)
    except ValueError:
        initial_select = 0

    result = clnch_listwindow.popMenu(
        main_window, sys.maxsize, 16, strings.CONFIG_THEME, theme_list, initial_select
    )
    result, _result_mod = clnch_listwindow._split_list_result(result)
    if result < 0:
        return

    ini_settings.THEME_NAME.set_text(clnch_ini, theme_list[result])

    main_window.reloadTheme()

    return False


def _configFontName(main_window):
    import clnch_fontlistwindow

    font_list = main_window.enumFonts()

    current_font_name = ini_settings.FONT_NAME.get_text(clnch_ini, default="")

    try:
        initial_select = font_list.index(current_font_name)
    except ValueError:
        initial_select = 0

    result = clnch_fontlistwindow.popFontMenu(main_window, font_list, initial_select)
    result, _result_mod = clnch_listwindow._split_list_result(result)
    if result < 0:
        return

    ini_settings.FONT_NAME.set_text(clnch_ini, font_list[result])

    main_window.updateFont()


def _configFontSize(main_window):
    value = _selectConfigValue(
        main_window, strings.CONFIG_FONT_SIZE,
        list(map(str, range(6, 33))),
        str(ini_settings.FONT_SIZE.get(clnch_ini)),
    )
    if value is None:
        return
    ini_settings.FONT_SIZE.set_text(clnch_ini, value)
    main_window.updateFont()


def _configMinWidth(main_window):
    value = _selectConfigValue(
        main_window, strings.CONFIG_MIN_SIZE,
        list(map(str, range(12, 81))),
        str(ini_settings.GEOMETRY_MIN_WIDTH.get(clnch_ini)),
    )
    if value is None:
        return
    ini_settings.GEOMETRY_MIN_WIDTH.set_text(clnch_ini, value)


def _configMaxWidth(main_window):
    value = _selectConfigValue(
        main_window, strings.CONFIG_MAX_SIZE,
        list(map(str, range(16, 161))),
        str(ini_settings.GEOMETRY_MAX_WIDTH.get(clnch_ini)),
    )
    if value is None:
        return
    ini_settings.GEOMETRY_MAX_WIDTH.set_text(clnch_ini, value)


def _configPosition(main_window):
    result = clnch_msgbox.popMessageBox(
        main_window,
        clnch_msgbox.MSGBOX_TYPE_YESNO,
        strings.POSITION_CONFIRM_TITLE,
        strings.POSITION_CONFIRM,
    )
    if result != clnch_msgbox.MSGBOX_RESULT_YES:
        return

    rect = list(main_window.getWindowRect())

    monitor_info_list = pyauto.Window.getMonitorInfo()

    for i in range(len(monitor_info_list)):
        monitor_info = monitor_info_list[i]
        if (
            monitor_info[0][0] <= rect[0] < monitor_info[0][2]
            and monitor_info[0][1] <= rect[1] < monitor_info[0][3]
        ):
            if rect[2] > monitor_info[0][2]:
                delta = rect[2] - monitor_info[0][2]
                rect[0] -= delta
                rect[2] -= delta
            if rect[3] > monitor_info[0][3]:
                delta = rect[3] - monitor_info[0][3]
                rect[1] -= delta
                rect[3] -= delta
            break
    else:
        left = monitor_info_list[0][0][0]
        top = monitor_info_list[0][0][1]
        rect = [left, top, left + rect[2] - rect[0], top + rect[3] - rect[1]]

    for i in range(len(monitor_info_list)):
        monitor_info = monitor_info_list[i]
        if (
            monitor_info[0][0] <= rect[0] < monitor_info[0][2]
            and monitor_info[0][1] <= rect[1] < monitor_info[0][3]
        ):
            ini_settings.GEOMETRY_MONITOR.set_text(clnch_ini, str(i))

            if rect[0] - monitor_info[0][0] <= monitor_info[0][2] - rect[2]:
                # Position relative to the monitor's left edge.
                ini_settings.GEOMETRY_X.set_text(clnch_ini, str(rect[0] - monitor_info[0][0]))
            else:
                # Position relative to the monitor's right edge.
                ini_settings.GEOMETRY_X.set_text(clnch_ini, str(rect[2] - monitor_info[0][2] - 1))

            if rect[1] - monitor_info[0][1] <= monitor_info[0][3] - rect[3]:
                # Position relative to the monitor's top edge.
                ini_settings.GEOMETRY_Y.set_text(clnch_ini, str(rect[1] - monitor_info[0][1]))
            else:
                # Position relative to the monitor's bottom edge.
                ini_settings.GEOMETRY_Y.set_text(clnch_ini, str(rect[3] - monitor_info[0][3] - 1))

            break

    clnch_msgbox.popMessageBox(
        main_window,
        clnch_msgbox.MSGBOX_TYPE_OK,
        strings.POSITION_SAVED_TITLE,
        strings.POSITION_SAVED,
    )


def _configTopMost(main_window):
    value = _selectConfigValue(
        main_window, strings.CONFIG_TOPMOST_TITLE,
        [(strings.TOPMOST_NORMAL, "0"), (strings.TOPMOST_ON, "1"),
         (strings.TOPMOST_ALWAYS, "2")],
        ini_settings.GEOMETRY_TOPMOST.get_text(clnch_ini),
    )
    if value is None:
        return
    ini_settings.GEOMETRY_TOPMOST.set_text(clnch_ini, value)
    main_window.updateTopMost()


def _configDirectorySeparator(main_window):
    value = _selectConfigValue(
        main_window, strings.CONFIG_SEPARATOR,
        [(strings.SEPARATOR_SLASH, "slash"), (strings.SEPARATOR_BACKSLASH, "backslash")],
        ini_settings.MISC_DIRECTORY_SEPARATOR.get(clnch_ini),
    )
    if value is None:
        return
    ini_settings.MISC_DIRECTORY_SEPARATOR.set_text(clnch_ini, value)
    ckit.setPathSlash(value == "slash")


def _configKeyMap(main_window):
    value = _selectConfigValue(
        main_window, strings.CONFIG_KEYMAP,
        [(strings.KEYMAP_101, "101"), (strings.KEYMAP_106, "106")],
        ini_settings.MISC_DEFAULT_KEYMAP.get(clnch_ini),
    )
    if value is None:
        return
    ini_settings.MISC_DEFAULT_KEYMAP.set_text(clnch_ini, value)
    main_window.configure()


def _configAutoComplete(main_window):
    value = _selectConfigValue(
        main_window, strings.CONFIG_AUTO_COMPLETE,
        [(strings.AUTO_COMPLETE_OFF, "0"), (strings.AUTO_COMPLETE_ON, "1")],
        ini_settings.MISC_AUTO_COMPLETE.get_text(clnch_ini),
    )
    if value is None:
        return
    ini_settings.MISC_AUTO_COMPLETE.set_text(clnch_ini, value)


def _configHotKeyAssign(main_window):
    RESULT_CANCEL = 0
    RESULT_OK = 1

    class HotKeyWindow(ckit.TextWindow):
        def __init__(self, x, y, parent_window, show=True):
            self.parent_window = parent_window

            ckit.TextWindow.__init__(
                self,
                x=x,
                y=y,
                width=35,
                height=2,
                origin=ORIGIN_X_CENTER | ORIGIN_Y_CENTER,
                parent_window=parent_window,
                show=show,
                bg_color=ckit.getColor("bg"),
                cursor0_color=ckit.getColor("cursor0"),
                cursor1_color=ckit.getColor("cursor1"),
                resizable=False,
                title=strings.CONFIG_HOTKEY,
                minimizebox=False,
                maximizebox=False,
                cursor=True,
                close_handler=self.onClose,
                keydown_handler=self.onKeyDown,
                dpi_handler=self.onDpi,
                move_handler=self.onMove,
            )

            with _cleanup_on_exit(self.destroy, error_only=True):
                self.setCursorPos(-1, -1)

                self.result = RESULT_CANCEL

                activate_vk = ini_settings.HOTKEY_ACTIVATE_VK.get(clnch_ini)
                activate_mod = ini_settings.HOTKEY_ACTIVATE_MOD.get(clnch_ini)

                self.activate_hotkey = ckit.HotKeyWidget(
                    self, 0, 0, self.width(), 1, activate_vk, activate_mod
                )

                self.layout(x, y)

                self.paint()

        def onClose(self):
            self.result = RESULT_CANCEL
            self.quit()

        def onEnter(self):
            if ckit.KeyEvent.isModifierKey(self.activate_hotkey.getValue()[0]):
                clnch_msgbox.popMessageBox(self, clnch_msgbox.MSGBOX_TYPE_OK,
                                          strings.ERROR_TITLE, strings.HOTKEY_MODIFIER_ONLY)
                return
            self.result = RESULT_OK
            self.quit()

        def onKeyDown(self, vk, mod):
            if mod == 0 and vk == VK_ESCAPE:
                self.result = RESULT_CANCEL
                self.quit()
            elif mod == 0 and vk == VK_RETURN:
                self.onEnter()
            elif mod == 0 and vk == VK_DELETE:
                self.activate_hotkey.onKeyDown(0, 0)
                self.paint()
            else:
                self.activate_hotkey.onKeyDown(vk, mod)

        def layout(self, x, y):
            max_width, max_height = ckit.getWindowSizeLimits(self)
            self._size_limits = (max_width, max_height)
            width = min(
                max_width,
                max(
                    35,
                    max(self.getStringWidth(line) for line in strings.HOTKEY_GUIDE.splitlines()) + 4,
                    self.getStringWidth(strings.CONFIG_EDIT_GUIDE) + 4,
                    self.getStringWidth(strings.CONFIG_HOTKEY) + 4,
                ),
            )
            self.guide_lines = ckit.splitLines(self, strings.HOTKEY_GUIDE, width - 4)
            self.control_lines = ckit.splitLines(self, strings.CONFIG_EDIT_GUIDE, width - 4)
            self.setPosSize(
                x,
                y,
                width,
                len(self.guide_lines) + len(self.control_lines) + 1,
                ORIGIN_X_CENTER | ORIGIN_Y_CENTER,
            )
            self.activate_hotkey.setPosSize(2, 0, width - 4, 1)

        def onDpi(self, scale):
            if not hasattr(self, "activate_hotkey"):
                return
            self.setFontFromFontObject(clnch_misc.getDialogFont(scale))
            rect = self.getWindowRect()
            self.layout((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
            ckit.fitWindowToWorkArea(self)
            self.paint()

        def onMove(self, x, y):
            if (
                hasattr(self, "guide_lines")
                and ckit.getWindowSizeLimits(self) != self._size_limits
            ):
                self.onDpi(self.getDisplayScaling())

        def paint(self):
            attr = ckit.Attribute(fg=ckit.getHintColor())
            for row in range(self.height()):
                self.putString(0, row, self.width(), 1, attr, " " * self.width())
            self.activate_hotkey.enableCursor(True)
            self.activate_hotkey.paint()
            if self.activate_hotkey.getValue()[0] == 0:
                label = ckit.adjustStringWidth(self, strings.HOTKEY_UNASSIGNED,
                                              self.width() - 4, ckit.ALIGN_CENTER)
                selected = ckit.Attribute(fg=ckit.getColor("select_fg"), bg=ckit.getColor("select_bg"))
                self.putString(2, 0, self.width() - 4, 1, selected, label)
            for row, line in enumerate(self.guide_lines, 1):
                self.putString(2, row, self.getStringWidth(line), 1, attr, line)
            for row, line in enumerate(self.control_lines, len(self.guide_lines) + 1):
                width = self.getStringWidth(line)
                self.putString(self.width() - width - 2, row, width, 1, attr, line)

        def getResult(self):
            if self.result:
                return [self.activate_hotkey.getValue()]
            else:
                return None

    was_enabled = main_window.isEnabled()
    pos = main_window.centerOfWindowInPixel()
    hotkey_window = HotKeyWindow(pos[0], pos[1], main_window, show=False)
    with clnch_misc._modal_dialog_scope(main_window, hotkey_window, was_enabled):
        clnch_misc.adjustWindowPosition(main_window, hotkey_window, default_up=False)
        hotkey_window.show(True)
        main_window.enable(False)
        hotkey_window.messageLoop()
        result = hotkey_window.getResult()

    if result is None:
        return

    if not main_window.updateHotKey(*result[0]):
        return

    ini_settings.HOTKEY_ACTIVATE_VK.set_text(clnch_ini, str(result[0][0]))
    ini_settings.HOTKEY_ACTIVATE_MOD.set_text(clnch_ini, str(result[0][1]))


def _configHotKeyBehavior(main_window):
    value = _selectConfigValue(
        main_window, strings.CONFIG_HOTKEY_BEHAVIOR,
        [(strings.HOTKEY_ACTIVATE, "activate"), (strings.HOTKEY_TOGGLE, "toggle")],
        ini_settings.MISC_HOTKEY_BEHAVIOR.get(clnch_ini),
    )
    if value is None:
        return
    ini_settings.MISC_HOTKEY_BEHAVIOR.set_text(clnch_ini, value)
    main_window.updateHotKey()


def _reloadConfigFile(main_window):
    main_window.command_Reload(None)
    return False


def _configAppearance(main_window):
    def build_items():
        separator = ini_settings.MISC_DIRECTORY_SEPARATOR.get_text(clnch_ini)
        topmost = ini_settings.GEOMETRY_TOPMOST.get_text(clnch_ini)
        return [
            _settingItem(strings.CONFIG_THEME,
                         ini_settings.THEME_NAME.get(clnch_ini), _configTheme),
            (strings.CONFIG_FONT_NAME.format(name=ini_settings.FONT_NAME.get(clnch_ini)),
             _configFontName),
            _settingItem(strings.CONFIG_FONT_SIZE,
                         ini_settings.FONT_SIZE.get(clnch_ini), _configFontSize),
            _settingItem(strings.CONFIG_MIN_WIDTH, strings.SETTING_CELLS.format(
                count=ini_settings.GEOMETRY_MIN_WIDTH.get(clnch_ini)), _configMinWidth),
            _settingItem(strings.CONFIG_MAX_WIDTH, strings.SETTING_CELLS.format(
                count=ini_settings.GEOMETRY_MAX_WIDTH.get(clnch_ini)), _configMaxWidth),
            _settingItem(strings.CONFIG_SEPARATOR, {
                "slash": strings.SEPARATOR_SLASH_NAME,
                "backslash": strings.SEPARATOR_BACKSLASH_NAME,
            }.get(separator, separator), _configDirectorySeparator),
            _settingItem(strings.CONFIG_TOPMOST, {
                "0": strings.TOPMOST_NORMAL,
                "1": strings.TOPMOST_ON,
                "2": strings.TOPMOST_ALWAYS,
            }.get(topmost, topmost), _configTopMost),
            (strings.CONFIG_POSITION, _configPosition),
        ]

    for items, select in _iterConfigMenu(main_window, strings.CONFIG_APPEARANCE, build_items):
        if items[select][1](main_window) is False:
            return False


_input_options = {
    "HISTORY_MODE": (
        strings.INPUT_HISTORY,
        [
            (strings.INPUT_HISTORY_OFF, "off"),
            (strings.INPUT_HISTORY_SESSION, "session"),
            (strings.INPUT_HISTORY_PERSISTENT, "persistent"),
        ],
    ),
    "COMPLETION_MODE": (
        strings.INPUT_COMPLETION,
        [
            (strings.INPUT_COMPLETION_OFF, "off"),
            (strings.INPUT_COMPLETION_COMMANDS, "commands"),
            (strings.INPUT_COMPLETION_STANDARD, "standard"),
        ],
    ),
    "CLEAR_ON_DEACTIVATE": (
        strings.INPUT_CLEAR,
        [(strings.INPUT_KEEP, False), (strings.INPUT_CLEAR_ON, True)],
    ),
    "SPACE_ACTION": (
        strings.INPUT_SPACE,
        [
            (strings.INPUT_SPACE_INSERT, "insert"),
            (strings.INPUT_SPACE_COMPLETE, "complete"),
        ],
    ),
    "TAB_ACTION": (
        strings.INPUT_TAB,
        [(strings.INPUT_TAB_CLEAR, "clear"), (strings.INPUT_TAB_COMPLETE, "complete")],
    ),
}


def _configInputSetting(main_window, name):
    title, choices = _input_options[name]
    current = main_window.input_settings[name]
    initial_select = next(i for i, item in enumerate(choices) if item[1] == current)
    if name == "HISTORY_MODE":
        choices = [(label + strings.HISTORY_RESET_NOTICE if value in ("off", "session") else label, value)
                   for label, value in choices]
    result = clnch_listwindow.popMenu(
        main_window, sys.maxsize, 16, title, choices, initial_select
    )
    result, _result_mod = clnch_listwindow._split_list_result(result)
    if result < 0 or choices[result][1] == current:
        return
    value = choices[result][1]
    settings = main_window.input_settings.copy()
    settings[name] = value
    if not main_window.applyInputSettings(settings):
        return
    stored = str(int(value)) if type(value) is bool else value
    clnch_inputconfig.SETTINGS[name].set_text(clnch_ini, stored)
    clnch_ini.write()


def _configInput(main_window):
    def build_items():
        keymap = ini_settings.MISC_DEFAULT_KEYMAP.get_text(clnch_ini)
        auto_complete = ini_settings.MISC_AUTO_COMPLETE.get_text(clnch_ini)
        items = [
            _settingItem(strings.CONFIG_KEYMAP, {
                "101": strings.KEYMAP_101, "106": strings.KEYMAP_106,
            }.get(keymap, keymap), _configKeyMap),
            _settingItem(strings.CONFIG_AUTO_COMPLETE, {
                "0": strings.AUTO_COMPLETE_OFF, "1": strings.AUTO_COMPLETE_ON,
            }.get(auto_complete, auto_complete), _configAutoComplete),
        ]
        for name, (title, choices) in _input_options.items():
            current = next(label for label, value in choices
                           if value == main_window.input_settings[name])
            items.append(_settingItem(
                title, current, lambda main_window, name=name: _configInputSetting(main_window, name)
            ))
        return items

    for items, select in _iterConfigMenu(main_window, strings.CONFIG_INPUT, build_items):
        items[select][1](main_window)


def _saveAltEnterSettings(main_window, key="", **changes):
    current = clnch_altenterconfig.get_settings(main_window, key)
    settings = dict(current, **changes)
    if settings == current:
        return True
    clnch_altenterconfig.validate(settings, key)
    previous_ini, previous_dirty = deepcopy(clnch_ini.ini), clnch_ini.dirty
    saved = False
    try:
        clnch_altenterconfig.write(clnch_ini, settings, key)
        clnch_ini.write()
        if clnch_ini.dirty or clnch_ini.read_failed:
            return False
        saved = True
    finally:
        if not saved:
            clnch_ini.ini, clnch_ini.dirty = previous_ini, previous_dirty
    if key:
        main_window.altenter_modified_settings[key] = settings
    else:
        main_window.altenter_settings = settings
    return True


def _configAltEnterAction(main_window, key=""):
    choices = [action for action in clnch_altenterconfig.ACTIONS if not key or action != "properties"]
    result = clnch_listwindow.popMenu(
        main_window, sys.maxsize, 16, clnch_altenterconfig.KEYS[key][1],
        [clnch_altenterconfig.ACTIONS[action] for action in choices],
        choices.index(clnch_altenterconfig.get_settings(main_window, key)["action"]),
    )
    result, _result_mod = clnch_listwindow._split_list_result(result)
    if result >= 0:
        _saveAltEnterSettings(main_window, key, action=choices[result])


def _configAltEnterTarget(main_window, key=""):
    settings = clnch_altenterconfig.get_settings(main_window, key).copy()
    if settings["action"] == "application":
        fields = (("executable", strings.ALT_ENTER_EXECUTABLE), ("arguments", strings.ALT_ENTER_ARGUMENTS))
        guide = strings.ALT_ENTER_APP_GUIDE
    else:
        fields = (("url", strings.ALT_ENTER_URL),)
        guide = strings.ALT_ENTER_WEB_GUIDE
    title = strings.ALT_ENTER_TARGET if settings["action"] == "application" else strings.ALT_ENTER_URL
    controls = strings.CONFIG_EDIT_FIELDS_GUIDE if len(fields) > 1 else strings.CONFIG_EDIT_GUIDE
    while True:
        width = min(72, max(
            max(map(main_window.getStringWidth, guide.splitlines())),
            main_window.getStringWidth(controls),
            *(main_window.getStringWidth(label) + main_window.getStringWidth(settings[name]) + 4
              for name, label in fields),
        ))
        was_enabled = main_window.isEnabled()
        dialog = ckit.Dialog(main_window, title, [
            *[ckit.Dialog.Edit(name, 0, width, label, settings[name]) for name, label in fields],
            ckit.Dialog.StaticText(0, guide),
            ckit.Dialog.StaticText(0, controls, align=ckit.ALIGN_RIGHT),
        ])
        with clnch_misc._modal_dialog_scope(main_window, dialog, was_enabled):
            dialog.font_handler = lambda scale: clnch_misc.getDialogFont(scale)
            clnch_misc.adjustWindowPosition(main_window, dialog, default_up=False)
            main_window.enable(False)
            dialog.messageLoop()
            result, values = dialog.getResult()
        if result != ckit.Dialog.RESULT_OK:
            return
        settings.update({name: values[name].strip() for name, _ in fields})
        try:
            if _saveAltEnterSettings(main_window, key, **settings):
                return
        except ValueError as error:
            clnch_msgbox.popMessageBox(main_window, clnch_msgbox.MSGBOX_TYPE_OK,
                                      strings.ERROR_INPUT_TITLE, str(error))


def _configAltEnterPriority(main_window):
    result = clnch_listwindow.popMenu(
        main_window, sys.maxsize, 16, strings.ALT_ENTER_PRIORITY,
        [strings.ALT_ENTER_NONE, strings.ALT_ENTER_ON],
        int(main_window.altenter_settings["properties_first"]),
    )
    result, _result_mod = clnch_listwindow._split_list_result(result)
    if result >= 0:
        _saveAltEnterSettings(main_window, properties_first=bool(result))


def _configValuePreview(main_window, value):
    return ckit.adjustStringWidth(main_window, value, 48, ellipsis=ckit.ELLIPSIS_MID).rstrip()


def _configAltEnterKey(main_window, key=""):
    def build_items():
        settings = clnch_altenterconfig.get_settings(main_window, key)
        items: list = [_settingItem(
            strings.ALT_ENTER_ACTION, clnch_altenterconfig.ACTIONS[settings["action"]],
            lambda window: _configAltEnterAction(window, key),
        )]
        if settings["action"] in ("application", "web"):
            if settings["action"] == "application":
                title = strings.ALT_ENTER_TARGET
                value = os.path.basename(settings["executable"])
            else:
                title = strings.ALT_ENTER_URL
                value = settings["url"]
            items.append(_settingItem(
                title, _configValuePreview(main_window, value or strings.DESTINATION_EMPTY),
                lambda window: _configAltEnterTarget(window, key),
            ))
            if not key:
                items.append(_settingItem(
                    strings.ALT_ENTER_PRIORITY,
                    strings.ALT_ENTER_ON if settings["properties_first"] else strings.ALT_ENTER_NONE,
                    _configAltEnterPriority,
                ))
        return items

    for items, select in _iterConfigMenu(main_window, clnch_altenterconfig.KEYS[key][1], build_items):
        items[select][1](main_window)


def _configAltEnter(main_window):
    def build_items():
        return [_settingItem(
            label, clnch_altenterconfig.ACTIONS[clnch_altenterconfig.get_settings(main_window, key)["action"]],
            lambda window, key=key: _configAltEnterKey(window, key),
        ) for key, (_section, label, _binding) in clnch_altenterconfig.KEYS.items()]

    for items, select in _iterConfigMenu(main_window, strings.CONFIG_ALT_ENTER, build_items):
        items[select][1](main_window)


def _saveModifierSettings(main_window, **changes):
    settings = dict(main_window.modifier_settings, **changes)
    if settings == main_window.modifier_settings:
        return
    clnch_modifierconfig.write(clnch_ini, settings)
    main_window.modifier_settings = settings
    clnch_ini.write()


def _editModifierRoot(main_window, title, value, allow_empty=False, explanation=()):
    label = strings.FOLDER_LABEL
    lines = (*explanation, strings.FOLDER_GUIDE, strings.CONFIG_EDIT_GUIDE)
    label_width = main_window.getStringWidth(label) + 2
    while True:
        # Dialog adds two cells on each side; include the edit's cursor margins.
        width = min(
            72,
            max(
                label_width + main_window.getStringWidth(value) + 2,
                max(map(main_window.getStringWidth, lines)),
            ),
        )
        was_enabled = main_window.isEnabled()
        dialog = ckit.Dialog(
            main_window,
            title,
            [
                *[ckit.Dialog.StaticText(0, line) for line in explanation],
                ckit.Dialog.Edit("path", 0, width, label, value),
                ckit.Dialog.StaticText(0, strings.FOLDER_GUIDE),
                ckit.Dialog.StaticText(0, strings.CONFIG_EDIT_GUIDE, align=ckit.ALIGN_RIGHT),
            ],
        )
        with clnch_misc._modal_dialog_scope(main_window, dialog, was_enabled):
            dialog.font_handler = lambda scale: clnch_misc.getDialogFont(scale)
            clnch_misc.adjustWindowPosition(main_window, dialog, default_up=False)
            main_window.enable(False)
            dialog.messageLoop()
            result, values = dialog.getResult()
        if result != ckit.Dialog.RESULT_OK:
            return None
        value = values["path"].strip()
        if not value and allow_empty:
            return ""
        try:
            clnch_modifierconfig.validate_root(value)
            return value
        except ValueError as error:
            clnch_msgbox.popMessageBox(
                main_window,
                clnch_msgbox.MSGBOX_TYPE_OK,
                strings.FOLDER_TITLE,
                str(error),
            )


def _configModifierSources(main_window):
    class SourceList(clnch_listwindow.ListWindow):
        def paint(self):
            if self.status_bar_layer:
                self.status_bar_layer.align = ckit.ALIGN_LEFT if self.isearch else ckit.ALIGN_RIGHT
            super().paint()

        def onClose(self):
            self.cancel()

    roots = list(main_window.modifier_settings["SOURCE_ROOTS"])
    status = strings.SOURCE_GUIDE
    select = 0
    while True:
        items = roots + [
            strings.BUTTON_ADD,
            strings.BUTTON_SAVE_BACK,
            strings.BUTTON_CANCEL,
        ]
        action = "edit"

        def keydown_hook(vk, mod):
            nonlocal action
            result = list_window.getResult()  # noqa: B023  # Window callbacks are cleared before the next iteration.
            index, _result_mod = clnch_listwindow._split_list_result(result)
            if vk == VK_INSERT and mod == 0:
                action = "add"
            elif 0 <= index < len(roots) and vk == VK_DELETE and mod == 0:
                action = "delete"
            elif (
                0 <= index < len(roots)
                and vk in (VK_UP, VK_DOWN)
                and mod == MODKEY_CTRL
            ):
                action = "up" if vk == VK_UP else "down"
            else:
                return False
            list_window.quit()  # noqa: B023  # Window callbacks are cleared before the next iteration.
            return True

        was_enabled = main_window.isEnabled()
        pos = main_window.centerOfWindowInPixel()
        list_window = SourceList(
            pos[0],
            pos[1],
            min(76, main_window.getStringWidth(status) + 2),
            1,
            sys.maxsize,
            16,
            main_window,
            False,
            strings.SOURCE_LIST_TITLE,
            items,
            initial_select=min(select, len(items) - 1),
            keydown_hook=keydown_hook,
            statusbar_handler=lambda width, index: status,
        )
        with clnch_misc._modal_dialog_scope(main_window, list_window, was_enabled):
            clnch_misc.adjustWindowPosition(main_window, list_window, default_up=False)
            list_window.show(True)
            main_window.enable(False)
            list_window.messageLoop()
            result = list_window.getResult()
        select, _result_mod = clnch_listwindow._split_list_result(result)
        if select < 0 or (action == "edit" and select == len(roots) + 2):
            return
        if action == "edit" and select == len(roots) + 1:
            _saveModifierSettings(main_window, SOURCE_ROOTS=tuple(roots))
            return
        if action == "delete":
            del roots[select]
        elif action in ("up", "down"):
            other = select + (-1 if action == "up" else 1)
            if 0 <= other < len(roots):
                roots[select], roots[other] = roots[other], roots[select]
                select = other
        else:
            adding = action == "add" or select == len(roots)
            value = _editModifierRoot(
                main_window,
                strings.SOURCE_TITLE,
                "" if adding else roots[select],
                explanation=(
                    strings.SOURCE_EXPLANATION,
                    strings.SOURCE_EXAMPLE,
                    strings.SOURCE_MAPPING_EXAMPLE,
                    strings.SOURCE_RESULT_EXAMPLE,
                ),
            )
            if value is not None:
                if adding:
                    roots.append(value)
                    select = len(roots) - 1
                else:
                    roots[select] = value


def _configModifier(main_window, modifier, label):
    select = 0
    while True:
        settings = main_window.modifier_settings
        action = settings[modifier + "_ACTION"]
        items = [
            strings.MODIFIER_ACTION.format(action=clnch_modifierconfig.ACTIONS[action])
        ]
        status = strings.MODIFIER_GUIDE
        if action == "mapped_folder":
            sources = settings["SOURCE_ROOTS"]
            destination = settings[modifier + "_DESTINATION_ROOT"]
            count = (
                strings.SOURCE_COUNT.format(count=len(sources))
                if sources
                else strings.SOURCE_EMPTY
            )
            items += [
                strings.SOURCE_SUMMARY.format(count=count),
                strings.DESTINATION_SUMMARY.format(
                    path=_configValuePreview(main_window, destination or strings.DESTINATION_EMPTY)
                ),
            ]
            if not sources:
                status = strings.SOURCE_MISSING
            elif not destination:
                status = strings.DESTINATION_MISSING
        select = clnch_listwindow.popMenu(
            main_window,
            sys.maxsize,
            16,
            strings.MODIFIER_DEFAULT_TITLE.format(modifier=label),
            items,
            min(select, len(items) - 1),
            statusbar_handler=lambda width, index: status,  # noqa: B023  # Window callbacks are cleared before the next iteration.
            min_width=min(76, main_window.getStringWidth(status) + 2),
        )
        select, _result_mod = clnch_listwindow._split_list_result(select)
        if select < 0:
            return
        if select == 0:
            choices = list(clnch_modifierconfig.ACTIONS.items())
            result = clnch_listwindow.popMenu(
                main_window,
                sys.maxsize,
                16,
                strings.MODIFIER_ACTION_TITLE.format(modifier=label),
                [item[1] for item in choices],
                [item[0] for item in choices].index(action),
            )
            result, _result_mod = clnch_listwindow._split_list_result(result)
            if result >= 0:
                _saveModifierSettings(
                    main_window, **{modifier + "_ACTION": choices[result][0]}
                )
        elif select == 1:
            _configModifierSources(main_window)
        else:
            value = _editModifierRoot(
                main_window,
                strings.MODIFIER_DESTINATION_TITLE.format(modifier=label),
                destination,
                allow_empty=True,
                explanation=(strings.DESTINATION_EXPLANATION,),
            )
            if value is not None:
                _saveModifierSettings(
                    main_window, **{modifier + "_DESTINATION_ROOT": value}
                )


def _configModifiers(main_window):
    def build_items():
        return [
            strings.SETTING_VALUE.format(
                title=label,
                value=clnch_modifierconfig.ACTIONS[main_window.modifier_settings[modifier + "_ACTION"]],
            )
            for modifier, label in clnch_modifierconfig.MODIFIERS
        ]

    status = strings.MODIFIER_GUIDE
    for items, select in _iterConfigMenu(
        main_window, strings.CONFIG_MODIFIERS, build_items,
        statusbar_handler=lambda width, index: status,
        min_width=min(76, main_window.getStringWidth(status) + 2),
    ):
        _configModifier(main_window, *clnch_modifierconfig.MODIFIERS[select])


def _hotKeyValue():
    vk = ini_settings.HOTKEY_ACTIVATE_VK.get(clnch_ini)
    if not vk:
        return strings.HOTKEY_UNASSIGNED
    mod = ini_settings.HOTKEY_ACTIVATE_MOD.get(clnch_ini)
    return ckit.KeyEvent.formatHotKey(vk, mod)


def _configHotKey(main_window):
    def build_items():
        behavior = ini_settings.MISC_HOTKEY_BEHAVIOR.get_text(clnch_ini)
        return [
            _settingItem(strings.CONFIG_HOTKEY_ASSIGN, _hotKeyValue(), _configHotKeyAssign),
            _settingItem(strings.CONFIG_HOTKEY_BEHAVIOR, {
                "activate": strings.HOTKEY_ACTIVATE, "toggle": strings.HOTKEY_TOGGLE,
            }.get(behavior, behavior), _configHotKeyBehavior),
        ]

    for items, select in _iterConfigMenu(main_window, strings.CONFIG_HOTKEY_OPTIONS, build_items):
        items[select][1](main_window)


def _configInactive(main_window):
    value = _selectConfigValue(
        main_window, strings.CONFIG_INACTIVE,
        [(strings.INACTIVE_EMPTY, "empty"), (strings.INACTIVE_CLOCK, "clock"),
         (strings.INACTIVE_HIDE, "hide")],
        ini_settings.MISC_INACTIVE_BEHAVIOR.get(clnch_ini),
    )
    if value is None:
        return
    ini_settings.MISC_INACTIVE_BEHAVIOR.set_text(clnch_ini, value)
    main_window.updateInactiveBehavior()


def _configLanguage(main_window):
    current = ini_settings.MISC_LANGUAGE.get(clnch_ini)
    value = _selectConfigValue(
        main_window, strings.CONFIG_LANGUAGE,
        [(strings.LANGUAGE_JAPANESE, "ja"), (strings.LANGUAGE_ENGLISH, "en")], "ja" if current == "ja" else "en",
    )
    if value is None or value == current:
        return
    previous_ini, previous_dirty = deepcopy(clnch_ini.ini), clnch_ini.dirty
    ini_settings.MISC_LANGUAGE.set_text(clnch_ini, value)
    clnch_ini.write()
    if clnch_ini.dirty or clnch_ini.read_failed:
        clnch_ini.ini, clnch_ini.dirty = previous_ini, previous_dirty
        return
    clnch_msgbox.popMessageBox(
        main_window, clnch_msgbox.MSGBOX_TYPE_OK, strings.CONFIG_LANGUAGE, strings.LANGUAGE_RESTART,
    )


def _languageValue():
    current = strings.get_language()
    saved = ini_settings.MISC_LANGUAGE.get(clnch_ini)
    next_language = "ja" if saved == "ja" else "en"
    labels = {"ja": strings.LANGUAGE_JAPANESE, "en": strings.LANGUAGE_ENGLISH}
    return (labels[current] if current == next_language else
            strings.LANGUAGE_PENDING.format(current=labels[current], next=labels[next_language]))


def _configDataPath(main_window):
    app_dir = os.path.dirname(sys.executable)
    try:
        current = clnch_execonfig.read(app_dir)
        items = [strings.DATA_APP_FOLDER, strings.DATA_USER_FOLDER]
        result = clnch_listwindow.popMenu(
            main_window, sys.maxsize, 16, strings.CONFIG_DATA, items, int(current)
        )
        result, _result_mod = clnch_listwindow._split_list_result(result)
        if result < 0 or bool(result) == current:
            return
        clnch_execonfig.write(app_dir, bool(result))
    except Exception as error:  # noqa: BLE001  # Report storage-setting failures without closing Config.
        clnch_msgbox.popMessageBox(
            main_window, clnch_msgbox.MSGBOX_TYPE_OK, strings.DATA_ERROR, str(error)
        )
        return False
    clnch_msgbox.popMessageBox(
        main_window,
        clnch_msgbox.MSGBOX_TYPE_OK,
        strings.CONFIG_DATA,
        strings.DATA_RESTART,
    )
    return False


def _dataPathValue():
    app_dir = os.path.dirname(sys.executable)
    portable = os.path.normcase(os.path.abspath(os.path.join(app_dir, "settings")))
    current = os.path.normcase(os.path.abspath(
        clnch_misc._require_data_path(ckit.dataPath(), for_abspath=True)
    )) != portable
    labels = (strings.DATA_APP_FOLDER, strings.DATA_USER_FOLDER)
    try:
        next_label = labels[clnch_execonfig.read(app_dir)]
    except Exception:  # noqa: BLE001  # Keep Config accessible when the next storage setting is unreadable.
        # Keep Config accessible; the storage submenu retains its existing error report.
        next_label = strings.DATA_UNREADABLE
    return (
        labels[current]
        if next_label == labels[current]
        else strings.DATA_PENDING.format(current=labels[current], next=next_label)
    )


def doConfigMenu(main_window):
    def build_items():
        inactive = ini_settings.MISC_INACTIVE_BEHAVIOR.get_text(clnch_ini)
        return [
            (strings.CONFIG_APPEARANCE, _configAppearance),
            (strings.CONFIG_INPUT, _configInput),
            (strings.CONFIG_MODIFIERS, _configModifiers),
            (strings.CONFIG_ALT_ENTER, _configAltEnter),
            _settingItem(strings.CONFIG_INACTIVE, {
                "empty": strings.INACTIVE_EMPTY,
                "clock": strings.INACTIVE_CLOCK,
                "hide": strings.INACTIVE_HIDE,
            }.get(inactive, inactive), _configInactive),
            (strings.CONFIG_HOTKEY_OPTIONS, _configHotKey),
            _settingItem(strings.CONFIG_LANGUAGE, _languageValue(), _configLanguage),
            _settingItem(strings.CONFIG_DATA, _dataPathValue(), _configDataPath),
            (strings.CONFIG_RELOAD, _reloadConfigFile),
        ]

    for items, select in _iterConfigMenu(main_window, strings.CONFIG_TITLE, build_items):
        if items[select][1](main_window) is False:
            return
