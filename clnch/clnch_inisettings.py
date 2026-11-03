"""Static launcher INI definitions; domain settings live beside their validation.

get() preserves the declared string/integer read. get_text() and set_text()
keep Config's raw string comparisons and existing string-write semantics.
No method applies settings or writes the INI file to disk.
Definitions require a default of the declared type, or None for no default.

"""

from dataclasses import dataclass
from typing import Protocol as _Protocol
from typing import overload as _overload


class _IniReader(_Protocol):
    def get[Default](
        self, section: str, option: str, default: Default | None = None,
    ) -> str | Default: ...

    def getint[Default](
        self, section: str, option: str, default: Default | None = None,
    ) -> int | Default: ...


@dataclass(frozen=True)
class IniSetting[Value: (str, int)]:
    section: str
    key: str
    default: Value | None
    value_type: type[str] | type[int] = str

    @_overload
    def __init__(
        self: "IniSetting[str]", section: str, key: str,
        default: str | None, value_type: type[str] = str,
    ) -> None: ...

    @_overload
    def __init__(
        self: "IniSetting[int]", section: str, key: str,
        default: int | None, value_type: type[int],
    ) -> None: ...

    def __init__(
        self, section: str, key: str, default: str | int | None,
        value_type: type[str] | type[int] = str,
    ) -> None:
        if value_type is not str and value_type is not int:
            raise TypeError("value_type must be str or int")
        if default is not None and type(default) is not value_type:
            raise TypeError("default must match value_type or be None")
        object.__setattr__(self, "section", section)
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "default", default)
        object.__setattr__(self, "value_type", value_type)

    @_overload
    def get(self: "IniSetting[str]", ini: _IniReader) -> str: ...

    @_overload
    def get(self: "IniSetting[int]", ini: _IniReader) -> int: ...

    def get(self, ini: _IniReader) -> str | int:
        getter = ini.getint if self.value_type is int else ini.get
        return getter(self.section, self.key, self.default)

    def get_text(self, ini: _IniReader, *, default: str | None = None) -> str:
        if default is None and self.default is not None:
            default = str(self.default)
        return ini.get(self.section, self.key, default)

    def set_text(self, ini, value):
        ini.set(self.section, self.key, value)


CONSOLE_HEIGHT = IniSetting('CONSOLE', 'height', 32, int)
CONSOLE_WIDTH = IniSetting('CONSOLE', 'width', 80, int)
CONSOLE_X = IniSetting('CONSOLE', 'x', 0, int)
CONSOLE_Y = IniSetting('CONSOLE', 'y', 0, int)
DEBUG_DETECT_BLOCK = IniSetting('DEBUG', 'detect_block', 0, int)
DEBUG_PRINT_ERRORINFO = IniSetting('DEBUG', 'print_errorinfo', 0, int)
FONT_NAME = IniSetting('FONT', 'name', 'MS Gothic')
FONT_SIZE = IniSetting('FONT', 'size', 16, int)
GEOMETRY_HEIGHT = IniSetting('GEOMETRY', 'height', None, int)
GEOMETRY_MAX_WIDTH = IniSetting('GEOMETRY', 'max_width', 80, int)
GEOMETRY_MIN_WIDTH = IniSetting('GEOMETRY', 'min_width', 18, int)
GEOMETRY_MONITOR = IniSetting('GEOMETRY', 'monitor', 0, int)
GEOMETRY_TOPMOST = IniSetting('GEOMETRY', 'topmost', 0, int)
GEOMETRY_WIDTH = IniSetting('GEOMETRY', 'width', None, int)
GEOMETRY_X = IniSetting('GEOMETRY', 'x', 0, int)
GEOMETRY_Y = IniSetting('GEOMETRY', 'y', 0, int)
HOTKEY_ACTIVATE_MOD = IniSetting('HOTKEY', 'activate_mod', 0, int)
HOTKEY_ACTIVATE_VK = IniSetting('HOTKEY', 'activate_vk', 0, int)
MISC_AUTO_COMPLETE = IniSetting('MISC', 'auto_complete', 0, int)
MISC_DEFAULT_KEYMAP = IniSetting('MISC', 'default_keymap', '106')
MISC_DIRECTORY_SEPARATOR = IniSetting('MISC', 'directory_separator', 'backslash')
MISC_HOTKEY_BEHAVIOR = IniSetting('MISC', 'hotkey_behavior', 'toggle')
MISC_INACTIVE_BEHAVIOR = IniSetting('MISC', 'inactive_behavior', 'clock')
MISC_ISEARCH_TYPE = IniSetting('MISC', 'isearch_type', 'partial')
MISC_LANGUAGE = IniSetting('MISC', 'language', 'en')
THEME_NAME = IniSetting('THEME', 'name', 'gray')

# History entries are an indexed sequence, not static settings.
COMMANDLINE_SECTION = "COMMANDLINE"
