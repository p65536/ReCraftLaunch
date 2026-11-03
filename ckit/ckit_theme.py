import configparser
import os
import re

from ckit import ckit_misc, ckit_resource

## @cond japanese
## @addtogroup theme テーマ機能
## @endcond
## @cond english
## @addtogroup theme Themes
## @endcond
## @addtogroup theme
## @{


default_theme_name = "black"
theme_name = default_theme_name
ini = None

COLOR_SECTION = "COLOR"
DEFAULT_COLORS = {
    "bg": "(0,0,0)",
    "fg": "(255,255,255)",
    "caret0": "(255,255,255)",
    "caret1": "(255,0,0)",
    "bar_fg": "(255,255,255)",
    "bar_error_fg": "(255,130,130)",
    "select_bg": "(130,130,130)",
    "select_fg": "(255,255,255)",
}
COLOR_FALLBACKS = {"choice_bg": "select_bg", "choice_fg": "select_fg"}


## \~japanese
# テーマを設定する
# 
#  @param name themes/内の拡張子なしテーマ名。
#  @param default_color テーマファイルにない色を補う名前からRGBタプルへの辞書。
#  @return None。共有の色設定を置換します。画面の再描画やフォント変更は行いません。
#  不足する基本色は既定値で補います。通常の利用者設定はConfigのテーマ選択を使ってください。
#
# \~english
# Set the theme
# 
#  @param name Theme filename without extension under themes/.
#  @param default_color Mapping of names to RGB tuples used when missing from the theme file.
#  @return None. Replace shared color settings without repainting windows or changing fonts.
#  Supply defaults for missing basic colors. Prefer Config theme selection for ordinary user settings.
#
# \~
def setTheme(name, default_color):
    global theme_name
    global ini

    theme_name = name

    filename = os.path.join(ckit_misc.getAppExePath(), "themes", theme_name + ".ini")

    ini = configparser.RawConfigParser()

    ini.add_section(COLOR_SECTION)

    for k in default_color.keys():  # noqa: SIM118  # Support mappings exposing keys and item access without iteration.
        ini.set(COLOR_SECTION, k, str(default_color[k]))

    ini.read(filename)

    for key, default in DEFAULT_COLORS.items():
        if not ini.has_option(COLOR_SECTION, key):
            ini.set(COLOR_SECTION, key, default)
    for key, fallback in COLOR_FALLBACKS.items():
        if not ini.has_option(COLOR_SECTION, key):
            ini.set(COLOR_SECTION, key, ini.get(COLOR_SECTION, fallback))


## \~japanese
# テーマをデフォルトの設定にする
# 
#  @return None。既定名blackと空の補完色辞書でsetThemeを呼びます。
#  既存ウィンドウの再描画を自動実行しません。
#
# \~english
# Reset the theme to its default configuration
# 
#  @return None. Call setTheme with the default black theme and an empty fallback mapping.
#  Do not automatically repaint existing windows.
#
# \~
def setThemeDefault():
    setTheme(default_theme_name, {})


## \~japanese
# テーマカラーを取得する
# 
#  @param name 色名（fg・bg・bar_fg等）。
#  @param section INIセクション。既定COLOR。
#  @return (r, g, b)の整数タプル。設定の取得失敗時は通知して(0, 0, 0)、文字列形式不正時はNone。
#  RGBを必要とするAPIへ渡す前にNoneの可能性を考慮してください。
#
# \~english
# Get a theme color
# 
#  @param name Color name, such as fg, bg or bar_fg.
#  @param section INI section, default COLOR.
#  @return Integer (r, g, b) tuple; on lookup failure report and return (0, 0, 0), or return None for malformed text.
#  Account for None before passing to an API requiring RGB.
#
# \~
def getColor(name, section=COLOR_SECTION):
    try:
        if ini is None:
            raise AttributeError(
                "'NoneType' object has no attribute 'get'", name="get", obj=None
            )
        s = ini.get(section, name)
    except Exception:  # noqa: BLE001  # Keep rendering available with the reported black fallback.
        print(ckit_resource.strings["color_not_found"], name)
        return (0, 0, 0)

    match_result = re.match(
        r"[ ]*\([ ]*([0-9]+)[ ]*,[ ]*([0-9]+)[ ]*,[ ]*([0-9]+)[ ]*\)[ ]*", s
    )
    if match_result:
        r = int(match_result.group(1))
        g = int(match_result.group(2))
        b = int(match_result.group(3))
        return (r, g, b)


def _require_rgb(color: tuple[int, int, int] | None) -> tuple[int, int, int]:
    if color is None:
        raise TypeError("'NoneType' object is not subscriptable")
    return color


## \~japanese
# 説明・情報表示用に前景色を背景色へ寄せた色を取得する
# 
#  @return fgを3、bgを1の重みで混ぜたRGBタプル。各要素は整数除算します。
#  @exception TypeError fgまたはbgの形式が不正でgetColorがNoneを返した場合。
#
# \~english
# Get a foreground color blended toward the background for explanatory text
# 
#  @return RGB tuple mixing three parts fg to one part bg with integer division.
#  @exception TypeError If fg or bg is malformed and getColor returns None.
#
# \~
def getHintColor():
    fg_color = getColor("fg")
    bg_color = getColor("bg")
    if fg_color is None or bg_color is None:
        raise TypeError("'NoneType' object is not iterable")
    return tuple((fg * 3 + bg) // 4 for fg, bg in zip(fg_color, bg_color))


## @} theme
