import datetime as _datetime
import math
import struct
from contextlib import ExitStack as _ExitStack
from typing import cast as _cast

import pyauto
from ckit import ckit_misc, ckit_textwindow, ckit_theme, ckitcore
from ckit.ckit_const import (
    LINE_BOTTOM,
    MODKEY_ALT,
    MODKEY_CTRL,
    MODKEY_SHIFT,
    MODKEY_WIN,
    ORIGIN_X_LEFT,
    ORIGIN_Y_TOP,
    VK_A,
    VK_BACK,
    VK_C,
    VK_CONTROL,
    VK_DELETE,
    VK_DOWN,
    VK_END,
    VK_ESCAPE,
    VK_H,
    VK_HOME,
    VK_K,
    VK_LCONTROL,
    VK_LEFT,
    VK_LMENU,
    VK_LSHIFT,
    VK_LWIN,
    VK_MENU,
    VK_NEXT,
    VK_PRIOR,
    VK_RCONTROL,
    VK_RETURN,
    VK_RIGHT,
    VK_RMENU,
    VK_RSHIFT,
    VK_RWIN,
    VK_SHIFT,
    VK_SPACE,
    VK_TAB,
    VK_UP,
    VK_V,
    VK_X,
    VK_Y,
    VK_Z,
)
from ckit.ckit_key import KeyEvent
from ckit.ckit_misc import _cleanup_on_exit

## @cond japanese
## @addtogroup widget ウィジェット機能
## @endcond
## @cond english
## @addtogroup widget Widgets
## @endcond
## @addtogroup widget
## @{

# ----------------------------------------------------------------------------------------------------------------------------
#
# ----------------------------------------------------------------------------------------------------------------------------


## \~japanese
# ウィジェットの基底クラス
# 
#  各種ウィジェットの基本機能を提供するクラスです。
# 
#  Widget(window, x, y, width, height)の位置・寸法は親TextWindowの表示セル単位です。
#  ウィジェット単体はメッセージループやフォーカス配送を所有しません。親からpaint・onKeyDown・onChar等を接続します。
#  showは可視状態だけを変えるため、必要なら親から再描画します。入力を受ける部品へenableCursor(True)を渡し、
#  非アクティブ時はFalseにしてキャレット・IME対象を切り替えます。資源を持つ派生部品はdestroyを呼びます。
#  通常の複数項目入力には資源・配送をまとめるDialogを使います。
#  @sa Dialog, EditWidget
#
# \~english
# Base class for widgets
# 
#  Provide common functionality for widgets.
# 
#  Widget(window, x, y, width, height) positions/sizes use parent TextWindow display cells.
#  A widget owns neither a message loop nor focus dispatch; connect paint/onKeyDown/onChar from the parent.
#  show only changes visibility, so repaint as needed. Call enableCursor(True) on the focused input control and False
#  when inactive to manage caret/IME targeting. Destroy derived controls that own resources.
#  Prefer Dialog for ordinary multi-field input and event/resource management.
#  @sa Dialog, EditWidget
#
# \~
class Widget:
    ## \~japanese
    # Widgetを構築します。引数・所有資源はクラス説明を参照してください。
    # \~english
    # Construct Widget; see the class description for arguments and owned resources.
    # \~
    def __init__(self, window, x, y, width, height):
        self.window = window
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.visible = True
        self.enable_cursor = False
        self.enable_ime = False
        self.ime_rect = None

    ## \~japanese
    # 可視フラグを設定します。基底実装は再描画・入力抑止・Planeの表示切替えを行いません。戻り値None。
    # \~english
    # Set the visibility flag only: no repaint, input suppression or plane visibility change. Return None.
    # \~
    def show(self, visible):
        self.visible = visible

    ## \~japanese
    # 親セル単位の位置と寸法を設定し、IME矩形を更新します。再描画しません。戻り値None。
    # \~english
    # Set position and size in parent cells and update the IME rectangle without repainting. Return None.
    # \~
    def setPosSize(self, x, y, width, height):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self._updateImeRect()

    ## \~japanese
    # フォーカス状態を設定します。False→True時に保存済みIME設定を親へ適用します。Falseだけでは親のIMEを無効化しません。
    # \~english
    # Set focus state. On False to True, apply the stored IME setting to the parent; False alone does not disable the parent IME.
    # \~
    def enableCursor(self, enable):
        if not self.enable_cursor and enable:
            self.window.enableIme(self.enable_ime)
        self.enable_cursor = enable
        self._updateImeRect()

    ## \~japanese
    # IME使用設定を保存し、フォーカス中だけ指定値を親へ反映します。再フォーカス時も保存値を使います。戻り値None。
    # \~english
    # Store the IME preference and apply it to the parent only while focused; refocusing also uses the stored value. Return None.
    # \~
    def enableIme(self, enable):
        if self.enable_cursor:
            self.window.enableIme(enable)
        self.enable_ime = enable
        self._updateImeRect()

    ## \~japanese
    # 部品左上からの相対セル矩形(left, top, right, bottom)を設定します。Noneなら部品全体。カーソル・IME有効時に親へ反映します。
    # \~english
    # Set a cell rectangle (left, top, right, bottom) relative to the widget, or None for the whole widget. Apply when cursor and IME are enabled.
    # \~
    def setImeRect(self, rect):
        self.ime_rect = rect
        self._updateImeRect()

    def _updateImeRect(self):
        if self.enable_cursor and self.enable_ime:
            if self.ime_rect is None:
                left, top = self.window.charToClient(self.x, self.y)
                right, bottom = self.window.charToClient(
                    self.x + self.width, self.y + self.height
                )
            else:
                left, top = self.window.charToClient(
                    self.x + self.ime_rect[0], self.y + self.ime_rect[1]
                )
                right, bottom = self.window.charToClient(
                    self.x + self.ime_rect[2], self.y + self.ime_rect[3]
                )

            rect = (left, top, right, bottom)
            self.window.setImeRect(rect)


# ----------------------------------------------------------------------------------------------------------------------------
#
# ----------------------------------------------------------------------------------------------------------------------------


## \~japanese
# ボタンウィジェット
# 
#
# messageは表示文字列、handlerは引数なしの関数またはNoneです。Space/EnterとonPushで同期呼出しし、戻り値は使いません。
# コンストラクターは描画します。高さによらず表示は1行です。ハンドラの例外は呼出し元へ届きます。
#
# \~english
# Button widget
# 
#
# message is the label; handler is a no-argument callback or None. Space/Enter and onPush call it synchronously; its return value is ignored.
# Construction paints the control on one row regardless of height. Callback exceptions propagate.
#
# \~
class ButtonWidget(Widget):
    ## \~japanese
    # ButtonWidgetを構築します。引数・所有資源はクラス説明を参照してください。
    # \~english
    # Construct ButtonWidget; see the class description for arguments and owned resources.
    # \~
    def __init__(self, window, x, y, width, height, message, handler=None):
        Widget.__init__(self, window, x, y, width, height)

        self.message = message
        self.handler = handler

        self.paint()

    ## \~japanese
    # 親から仮想キーvk・MODKEY_*のmodを配送します。戻り値None。
    # \~english
    # Route a virtual key vk and MODKEY_* mod from the parent. Return None.
    # \~
    def onKeyDown(self, vk, mod):

        if vk == VK_SPACE or vk == VK_RETURN:
            self.onPush()

        self.paint()

    ## \~japanese
    # handlerがあれば引数なしで呼びます。戻り値None、コールバックの戻り値は無視します。
    # \~english
    # Call handler with no arguments when set. Return None; ignore the callback return value.
    # \~
    def onPush(self):
        if self.handler:
            self.handler()

    ## \~japanese
    # 現在状態を親へ描画します。戻り値None。親の描画・フォーカス更新から呼びます。
    # \~english
    # Paint current state into the parent; return None. Call from host painting/focus updates.
    # \~
    def paint(self):
        if self.enable_cursor:
            attr = ckitcore.Attribute(
                fg=ckit_theme.getColor("select_fg"), bg=ckit_theme.getColor("select_bg")
            )
            self.window.setCursorPos(-1, -1)
        else:
            attr = ckitcore.Attribute(fg=ckit_theme.getColor("fg"))

        self.window.putString(self.x, self.y, self.width, 1, attr, self.message)


# ----------------------------------------------------------------------------------------------------------------------------
#
# ----------------------------------------------------------------------------------------------------------------------------


## \~japanese
# チェックボックスウィジェット
# 
#
# messageは表示文字列、checkは初期値です。Spaceで真偽を反転します。getValueで結果を取得します。
# 初期値はそのまま保持し、最初の反転後はboolになります。構築時に1行描画します。
#
# \~english
# Checkbox widget
# 
#
# message is the label; check is the initial value. Space toggles truth; getValue retrieves it.
# The initial object is retained; after the first toggle the value is bool. Construction paints one row.
#
# \~
class CheckBoxWidget(Widget):
    ## \~japanese
    # CheckBoxWidgetを構築します。引数・所有資源はクラス説明を参照してください。
    # \~english
    # Construct CheckBoxWidget; see the class description for arguments and owned resources.
    # \~
    def __init__(self, window, x, y, width, height, message, check):
        Widget.__init__(self, window, x, y, width, height)

        self.message = message
        self.check = check

        self.paint()

    ## \~japanese
    # 親から仮想キーvk・MODKEY_*のmodを配送します。対象キーならTrue、その他はNone。
    # \~english
    # Route a virtual key vk and MODKEY_* mod from the parent. Return True for handled keys, otherwise None.
    # \~
    def onKeyDown(self, vk, mod):

        if vk == VK_SPACE:
            self.check = not self.check
            self.paint()
            return True

    ## \~japanese
    # 現在状態を親へ描画します。戻り値None。親の描画・フォーカス更新から呼びます。
    # \~english
    # Paint current state into the parent; return None. Call from host painting/focus updates.
    # \~
    def paint(self):
        if self.enable_cursor:
            attr = ckitcore.Attribute(
                fg=ckit_theme.getColor("select_fg"), bg=ckit_theme.getColor("select_bg")
            )
            self.window.setCursorPos(-1, -1)
        else:
            attr = ckitcore.Attribute(fg=ckit_theme.getColor("fg"))

        mark = "[x]" if self.check else "[ ]"
        self.window.putString(self.x, self.y, self.width, 1, attr, mark + self.message)

    ## \~japanese
    # 現在のチェック値を返します。
    # \~english
    # Return the current check value.
    # \~
    def getValue(self):
        return self.check


# ----------------------------------------------------------------------------------------------------------------------------
#
# ----------------------------------------------------------------------------------------------------------------------------


## \~japanese
# 択一ウィジェット
# 
#  複数の選択肢から一つを選択するために使用するウィジェットです。
# 
#
# messageはラベル、item_listは選択肢文字列のシーケンス、initial_selectは0始まりの番号です。
# 空でない選択肢と有効な初期番号を渡してください。左右キーは両端で停止します。
# 幅が足りないと選択肢を縦配置・折返しし、構築時とsetPosSize時に指定heightを必要な高さまで拡張します。
# itemRectsは親セル座標の(x, y, width, height, 表示行リスト)を返す配置補助です。
#
# \~english
# Single-choice widget
# 
#  Select one of several choices.
# 
#
# message is a label; item_list is a sequence of choice strings; initial_select is a zero-based index.
# Supply nonempty choices and a valid initial index. Left/Right stop at the ends.
# Narrow widths stack/wrap choices; construction and setPosSize increase the supplied height to fit.
# itemRects is a layout helper returning (x, y, width, height, display_lines) in parent cells.
#
# \~
class ChoiceWidget(Widget):
    ## \~japanese
    # ChoiceWidgetを構築します。引数・所有資源はクラス説明を参照してください。
    # \~english
    # Construct ChoiceWidget; see the class description for arguments and owned resources.
    # \~
    def __init__(self, window, x, y, width, height, message, item_list, initial_select):
        Widget.__init__(self, window, x, y, width, height)

        self.message = message
        self.item_list = item_list
        self.select = initial_select
        self.row_step = 1
        self.setPosSize(x, y, width, height)

        self.paint()

    ## \~japanese
    # 位置と幅を更新し、指定heightを下限として折返し後の高さを再計算します。再描画しません。
    # \~english
    # Update position and width, recalculating wrapped height with the supplied height as a minimum. Do not repaint.
    # \~
    def setPosSize(self, x, y, width, height):
        self.x, self.y, self.width = x, y, width
        height = max(
            height,
            max((y + h for x, y, w, h, parts in self.itemRects()), default=y) - y,
        )
        Widget.setPosSize(self, x, y, width, height)

    ## \~japanese
    # 親から仮想キーvk・MODKEY_*のmodを配送します。対象キーならTrue、その他はNone。
    # \~english
    # Route a virtual key vk and MODKEY_* mod from the parent. Return True for handled keys, otherwise None.
    # \~
    def onKeyDown(self, vk, mod):

        if vk == VK_LEFT:
            self.select -= 1
            if self.select < 0:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
                self.select = 0
            self.paint()
            return True
        elif vk == VK_RIGHT:
            self.select += 1
            if self.select > len(self.item_list) - 1:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
                self.select = len(self.item_list) - 1
            self.paint()
            return True

    ## \~japanese
    # 選択肢ごとの(x, y, width, height, 表示行リスト)を親セル座標で返します。row_stepは折返し/縦配置時の行間隔で、既定1です。
    # \~english
    # Return each choice's (x, y, width, height, display_lines) in parent cells. row_step is the wrapped/stacked row spacing, default one.
    # \~
    def itemRects(self):
        x = self.x + self.window.getStringWidth(self.message) + 2
        available = max(2, self.width - (x - self.x))
        widths = [self.window.getStringWidth(item) for item in self.item_list]
        horizontal = sum(widths) + 2 * (len(widths) - 1) <= available
        y = self.y
        rects = []
        for item, width in zip(self.item_list, widths):
            lines = ckit_misc.splitLines(self.window, item, available) or [""]
            height = (len(lines) - 1) * self.row_step + 1
            rects.append((x, y, min(width, available), height, lines))
            if horizontal:
                x += width + 2
            else:
                y += len(lines) * self.row_step
        return rects

    ## \~japanese
    # 現在状態を親へ描画します。戻り値None。親の描画・フォーカス更新から呼びます。
    # \~english
    # Paint current state into the parent; return None. Call from host painting/focus updates.
    # \~
    def paint(self):
        x = self.x

        message_width = self.window.getStringWidth(self.message)
        self.window.putString(
            x,
            self.y,
            message_width,
            1,
            ckitcore.Attribute(fg=ckit_theme.getColor("fg")),
            self.message,
        )
        for i, (x, y, width, height, lines) in enumerate(self.itemRects()):
            if self.select == i:
                if self.enable_cursor:
                    attr = ckitcore.Attribute(
                        fg=ckit_theme.getColor("select_fg"),
                        bg=ckit_theme.getColor("select_bg"),
                    )
                    self.window.setCursorPos(-1, -1)
                else:
                    attr = ckitcore.Attribute(
                        fg=ckit_theme.getColor("choice_fg"),
                        bg=ckit_theme.getColor("choice_bg"),
                    )
            else:
                attr = ckitcore.Attribute(fg=ckit_theme.getColor("fg"))

            for row, line in enumerate(lines):
                self.window.putString(x, y + row * self.row_step, width, 1, attr, line)

    ## \~japanese
    # 現在の0始まりの選択番号を返します。
    # \~english
    # Return the current zero-based choice index.
    # \~
    def getValue(self):
        return self.select


# ----------------------------------------------------------------------------------------------------------------------------
#
# ----------------------------------------------------------------------------------------------------------------------------


## \~japanese
# 色選択ウィジェット
# 
#
# messageはラベル、colorは各成分0〜255のRGBタプルです。Space/EnterでWindowsの色選択を開き、取消時は色を保持します。
# ラベルは先頭5セルを除く幅に収め、widthが5以下なら描画しません。色見本は従来どおり4セル幅です。
# color_tableは全インスタンスで共有する16色のパレットです。構築時に2枚のImagePlaneを確保します。
# 親を破棄する前にdestroy()で両Planeを解放します。構築途中の失敗でも取得済みPlaneを解放します。
# show(False)は両Planeも隠します。既存のラベル文字列は親の再描画で消去してください。
#
# \~english
# Color-selection widget
# 
#
# message is a label; color is an RGB tuple with components 0..255. Space/Enter opens the Windows color dialog; cancellation retains the color.
# The label fits the width after the first five cells; widths of five or less draw no label. The swatch retains its four-cell width.
# color_table is a shared 16-color palette. Construction allocates two ImagePlanes.
# Call destroy() before the parent to release both planes; partial construction failures also release acquired planes.
# show(False) also hides both planes. Erase previously drawn label text by repainting the parent.
#
# \~
class ColorWidget(Widget):
    color_table = (
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
    )

    ## \~japanese
    # ColorWidgetを構築します。引数・所有資源はクラス説明を参照してください。
    # \~english
    # Construct ColorWidget; see the class description for arguments and owned resources.
    # \~
    def __init__(self, window, x, y, width, height, message, color):
        Widget.__init__(self, window, x, y, width, height)

        self.frame_plane = None
        self.color_plane = None
        with _cleanup_on_exit(self.destroy, error_only=True):
            self.frame_plane_size = self.window.getCharSize()
            self.frame_plane_size = (
                self.frame_plane_size[0] * 4 - 1,
                self.frame_plane_size[1] - 1,
            )
            self.frame_plane = ckitcore.ImagePlane(
                self.window, (0, 0), self.frame_plane_size, 1
            )
            self.color_plane_size = (
                self.frame_plane_size[0] - 2,
                self.frame_plane_size[1] - 2,
            )
            self.color_plane = ckitcore.ImagePlane(
                self.window, (0, 0), self.color_plane_size, 0
            )

            self.message = message
            self.color = color

            self.paint()

    ## \~japanese
    # 所有Planeをすべて解放します。繰返し呼出し可能。親は破棄しません。
    # \~english
    # Release all owned planes; repeated calls are safe. Do not destroy the parent.
    # \~
    def destroy(self):
        with _ExitStack() as cleanup:
            for name in ("frame_plane", "color_plane"):
                plane = getattr(self, name)
                if plane is not None:
                    setattr(self, name, None)
                    cleanup.enter_context(_cleanup_on_exit(plane.destroy))

    ## \~japanese
    # 可視状態を所有Planeへ反映します。既存のラベルは親から再描画してください。
    # \~english
    # Apply visibility to owned planes; repaint the previous label from the parent.
    # \~
    def show(self, visible):
        Widget.show(self, visible)
        _cast(ckitcore.ImagePlane, self.frame_plane).show(visible)
        _cast(ckitcore.ImagePlane, self.color_plane).show(visible)

    ## \~japanese
    # 親から仮想キーvk・MODKEY_*のmodを配送します。戻り値None。
    # \~english
    # Route a virtual key vk and MODKEY_* mod from the parent. Return None.
    # \~
    def onKeyDown(self, vk, mod):

        if vk == VK_SPACE or vk == VK_RETURN:
            import clnch_native

            result, color, ColorWidget.color_table = clnch_native.chooseColor(
                self.window.getHWND(), self.color, ColorWidget.color_table
            )
            if result:
                self.color = color
        self.paint()

    ## \~japanese
    # 現在状態を親へ描画します。戻り値None。親の描画・フォーカス更新から呼びます。
    # \~english
    # Paint current state into the parent; return None. Call from host painting/focus updates.
    # \~
    def paint(self):
        if not self.visible:
            return

        pos1 = self.window.charToClient(self.x + 0, self.y)
        pos2 = self.window.charToClient(self.x + 4, self.y + 1)

        _cast(ckitcore.ImagePlane, self.frame_plane).setPosition(
            (
                (pos1[0] + pos2[0] - self.color_plane_size[0]) // 2,
                (pos1[1] + pos2[1] - self.color_plane_size[1]) // 2,
            )
        )
        bg_color = ckit_theme._require_rgb(ckit_theme.getColor("bg"))
        _cast(ckitcore.ImagePlane, self.frame_plane).setImage(
            ckitcore.Image.fromBytes(
                (1, 1),
                struct.pack(
                    "BBBB",
                    bg_color[0] ^ 0xFF,
                    bg_color[1] ^ 0xFF,
                    bg_color[2] ^ 0xFF,
                    0xFF,
                ),
            )
        )

        _cast(ckitcore.ImagePlane, self.color_plane).setPosition(
            (
                (pos1[0] + pos2[0] - self.color_plane_size[0]) // 2 + 1,
                (pos1[1] + pos2[1] - self.color_plane_size[1]) // 2 + 1,
            )
        )
        _cast(ckitcore.ImagePlane, self.color_plane).setImage(
            ckitcore.Image.fromBytes(
                (1, 1),
                struct.pack("BBBB", self.color[0], self.color[1], self.color[2], 0xFF),
            )
        )

        if self.enable_cursor:
            attr = ckitcore.Attribute(
                fg=ckit_theme.getColor("select_fg"), bg=ckit_theme.getColor("select_bg")
            )
            self.window.setCursorPos(-1, -1)
        else:
            attr = ckitcore.Attribute(fg=ckit_theme.getColor("fg"))

        self.window.putString(self.x + 5, self.y, max(0, self.width - 5), 1, attr, self.message)

    ## \~japanese
    # 現在のRGBタプルを返します。取消では変わりません。
    # \~english
    # Return the current RGB tuple; cancellation does not change it.
    # \~
    def getValue(self):
        return self.color


# ----------------------------------------------------------------------------------------------------------------------------
#
# ----------------------------------------------------------------------------------------------------------------------------


## \~japanese
# ホットキー設定ウィジェット
# 
#
# vkはWindows仮想キーコード、modはMODKEY_*のビット和です。キー入力のたびに値を置換し、修飾キー単独ならそのキー自身の修飾ビットを除きます。
# 表示はKeyEvent.formatHotKeyを使い、左右を区別しない修飾キーと配列に応じた記号を表示します。
# getValueは2要素の整数リスト [vk, mod] を返します。OSへのホットキー登録は行わないため、取得後に親が登録してください。
#
# \~english
# Hotkey-assignment widget
# 
#
# vk is a Windows virtual-key code and mod is a bitwise combination of MODKEY_* values. Each key replaces the value; a modifier key clears its own modifier bit.
# Display uses KeyEvent.formatHotKey with side-independent modifiers and layout-specific symbols.
# getValue returns a two-element integer list [vk, mod]. This control does not register an OS hotkey; the owner registers the result.
#
# \~
class HotKeyWidget(Widget):
    ## \~japanese
    # HotKeyWidgetを構築します。引数・所有資源はクラス説明を参照してください。
    # \~english
    # Construct HotKeyWidget; see the class description for arguments and owned resources.
    # \~
    def __init__(self, window, x, y, width, height, vk, mod):
        Widget.__init__(self, window, x, y, width, height)

        self.vk = vk
        self.mod = mod

        self.paint()

    ## \~japanese
    # 親から仮想キーvk・MODKEY_*のmodを配送します。戻り値None。
    # \~english
    # Route a virtual key vk and MODKEY_* mod from the parent. Return None.
    # \~
    def onKeyDown(self, vk, mod):

        if vk == VK_LCONTROL or vk == VK_RCONTROL or vk == VK_CONTROL:
            mod &= ~MODKEY_CTRL
        elif vk == VK_LMENU or vk == VK_RMENU or vk == VK_MENU:
            mod &= ~MODKEY_ALT
        elif vk == VK_LSHIFT or vk == VK_RSHIFT or vk == VK_SHIFT:
            mod &= ~MODKEY_SHIFT
        elif vk == VK_LWIN or vk == VK_RWIN:
            mod &= ~MODKEY_WIN

        self.vk = vk
        self.mod = mod

        self.paint()

    ## \~japanese
    # 現在状態を親へ描画します。戻り値None。親の描画・フォーカス更新から呼びます。
    # \~english
    # Paint current state into the parent; return None. Call from host painting/focus updates.
    # \~
    def paint(self):
        if self.enable_cursor:
            attr = ckitcore.Attribute(
                fg=ckit_theme.getColor("select_fg"), bg=ckit_theme.getColor("select_bg")
            )
            self.window.setCursorPos(-1, -1)
        else:
            attr = ckitcore.Attribute(fg=ckit_theme.getColor("fg"))

        s = KeyEvent.formatHotKey(self.vk, self.mod)
        if self.width < 2 and self.window.getStringWidth(s) > self.width:
            s = "⋯" if self.width == 1 else ""
        s = ckit_misc.adjustStringWidth(
            self.window, s, self.width, ckit_misc.ALIGN_CENTER, ckit_misc.ELLIPSIS_RIGHT
        )

        self.window.putString(self.x, self.y, self.width, 1, attr, s)

    ## \~japanese
    # 現在の値を2要素の整数リスト [vk, mod] で返します。
    # \~english
    # Return the current values as a two-element integer list [vk, mod].
    # \~
    def getValue(self):
        return [self.vk, self.mod]


# ----------------------------------------------------------------------------------------------------------------------------
#
# ----------------------------------------------------------------------------------------------------------------------------


class action_Insert:
    def __init__(self, pos, text):
        self.pos = pos
        self.text = text


class action_Delete:
    def __init__(self, pos, text):
        self.pos = pos
        self.text = text


class action_Back:
    def __init__(self, pos, text):
        self.pos = pos
        self.text = text


class action_Replace:
    def __init__(self, pos, old, new):
        self.pos = pos
        self.old = old
        self.new = new


## \~japanese
# テキスト編集ウィジェット
# 
#  親TextWindowに置く1行入力部品です。通常のランチャー入力にはMainWindow.commandLine、複数項目にはDialog.Editを使えます。
#  text・getText/setTextは文字列、selectionは[anchor, cursor]の文字位置です。Noneなら末尾のカーソルになります。
#  update_handler(info)はNoneまたは真なら許可、Falseと等しい値（0を含む）なら拒否します。MainWindow.commandLineの更新ハンドラとは異なります。
#  infoはtext・selectionとselectionLeft()/selectionRight()を持ち、必要なら書換えます。
#  candidate_handler(info)は(候補文字列リスト, 置換開始位置)を返します。candidate_remove_handler(text)は削除の成否を返します。
#  word_break_handler(text, position, direction)は移動先の文字位置を返します。auto_completeは候補の自動挿入設定です。
#  no_bgは背景描画を省略するか、margin1/margin2は横スクロールの余白セル数です。
#  破棄時はdestroyで候補窓も解放します。親はキー・文字・有効状態・移動時の候補閉鎖を配送してください。
#  候補窓の生成・onListSelChange・appendUndoとaction_*は内部の補完配送/履歴処理です。通常は直接呼びません。
#  @sa Dialog
#
# \~english
# Text editor widget
# 
#  Single-line control on a parent TextWindow. Prefer MainWindow.commandLine for launcher input or Dialog.Edit for forms.
#  text/getText/setText use strings; selection is [anchor, cursor] in string positions, with None placing the cursor at the end.
#  update_handler(info) permits updates on None or true, rejects values equal to False (including 0); this differs from MainWindow.commandLine.
#  info has text/selection and selectionLeft()/selectionRight(), and can be modified.
#  candidate_handler(info) returns (list_of_candidate_strings, replacement_start); candidate_remove_handler(text) returns removal success.
#  word_break_handler(text, position, direction) returns a character position. auto_complete controls automatic candidate insertion.
#  no_bg skips background painting; margin1/margin2 are horizontal scroll margins in cells.
#  Call destroy to release the completion window. The parent must route keys, characters, activation and movement updates.
#  Candidate creation, onListSelChange, appendUndo and action_* are internal completion/history plumbing; normally do not call them.
#  @sa Dialog
#
# \~
class EditWidget(Widget):
    candidate_list_min_width = 10
    candidate_list_min_height = 1
    candidate_list_max_width = 80
    candidate_list_max_height = 16

    ## \~japanese
    # 編集候補。textは更新後文字列、selectionは[anchor, cursor]。ハンドラで書換えできます。
    # \~english
    # Proposed edit: text is new text; selection is [anchor, cursor]. Callbacks can modify both.
    # \~
    class UpdateInfo:
        ## \~japanese
        # text/selectionをコピーせず保持します。
        # \~english
        # Retain text/selection without copying.
        # \~
        def __init__(self, text, selection):
            self.text = text
            self.selection = selection

        ## \~japanese
        # 小さい方の選択位置を返します。
        # \~english
        # Return the smaller selection position.
        # \~
        def selectionLeft(self):
            return min(self.selection[0], self.selection[1])

        ## \~japanese
        # 大きい方の選択位置を返します。
        # \~english
        # Return the larger selection position.
        # \~
        def selectionRight(self):
            return max(self.selection[0], self.selection[1])

    ## \~japanese
    # EditWidgetを構築します。引数・所有資源はクラス説明を参照してください。
    # \~english
    # Construct EditWidget; see the class description for arguments and owned resources.
    # \~
    def __init__(
        self,
        window,
        x,
        y,
        width,
        height,
        text,
        selection=None,
        margin1=1,
        margin2=12,
        auto_complete: int = False,
        no_bg=False,
        autofix_list=None,
        update_handler=None,
        candidate_handler=None,
        candidate_remove_handler=None,
        word_break_handler=None,
    ):
        Widget.__init__(self, window, x, y, width, height)

        self.enableIme(True)

        self.text = text
        if selection is None:
            selection = [len(text), len(text)]
        self.selection = selection
        if margin1 > self.width // 2:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
            margin1 = self.width // 2
        if margin2 > self.width // 2:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
            margin2 = self.width // 2
        self.margin1 = margin1
        self.margin2 = margin2
        self.auto_complete = auto_complete
        self.vk_complete = [VK_SPACE]
        self.scroll_pos = -self.margin1
        self.no_bg = no_bg
        self.autofix_list = autofix_list
        # None allows an update; False and numeric zero reject it.
        self.update_handler = update_handler
        self.candidate_handler = candidate_handler
        self.candidate_remove_handler = candidate_remove_handler
        if word_break_handler:
            self.word_break_handler = word_break_handler
        else:
            self.word_break_handler = ckit_misc.wordbreak_Filename

        self.undo_list = []
        self.redo_list = []
        self.last_action = None

        self.list_window = None
        try:
            if candidate_handler:
                self.list_window = self.createCandidateWindow()
            self.list_window_base_len = 0
            self.list_window_prepared_info = None
            self.list_window_possize_info = None

            self.makeVisible(self.selection[1])

            self.paint()
        except BaseException as error:
            try:
                self.destroy()
            except BaseException as cleanup_error:  # noqa: BLE001  # Keep the constructor failure while releasing a partially initialized candidate window.
                error.add_note(f"EditWidget cleanup failed: {cleanup_error!r}")
            raise

    ## \~japanese
    # 保持する候補窓を破棄します。親の破棄前に呼びます。戻り値None。
    # \~english
    # Destroy the retained completion window before destroying the parent. Return None.
    # \~
    def destroy(self):
        if self.list_window:
            self.list_window.destroy()

    def createCandidateWindow(self):
        return CandidateWindow(
            0,
            0,
            EditWidget.candidate_list_min_width,
            EditWidget.candidate_list_min_height,
            EditWidget.candidate_list_max_width,
            EditWidget.candidate_list_max_height,
            self.window,
            selchange_handler=self.onListSelChange,
        )

    ## \~japanese
    # 自動挿入設定をそのまま保存します。現在の文字列・候補は更新しません。
    # \~english
    # Store the automatic insertion setting as supplied without updating current text/candidates.
    # \~
    def setAutoComplete(self, auto_complete):
        self.auto_complete = auto_complete

    ## \~japanese
    # 保存済み自動挿入設定を返します。boolへの変換はしません。
    # \~english
    # Return the stored automatic insertion setting without bool conversion.
    # \~
    def getAutoComplete(self):
        return self.auto_complete

    def appendUndo(self, action):
        if self.last_action is not None:
            self.undo_list.append(self.last_action)
            self.redo_list = []
        self.last_action = action

    ## \~japanese
    # 直前の編集を取り消します。更新ハンドラは拒否できます。履歴なし・実行後とも戻り値None。
    # \~english
    # Undo the last edit; the update handler may reject it. Return None both with no history and after an attempt.
    # \~
    def undo(self):
        self.appendUndo(None)

        if len(self.undo_list) == 0:
            return

        action = self.undo_list[-1]

        if isinstance(action, action_Insert):

            update_info = EditWidget.UpdateInfo(
                self.text[: action.pos] + self.text[action.pos + len(action.text) :],
                [action.pos, action.pos],
            )

        elif isinstance(action, action_Delete) or isinstance(action, action_Back):  # noqa: SIM101  # Retain short-circuit evaluation; excluded from cleanup for performance.

            update_info = EditWidget.UpdateInfo(
                self.text[: action.pos] + action.text + self.text[action.pos :],
                [action.pos + len(action.text), action.pos + len(action.text)],
            )

        elif isinstance(action, action_Replace):

            update_info = EditWidget.UpdateInfo(
                self.text[: action.pos]
                + action.old
                + self.text[action.pos + len(action.new) :],
                [action.pos + len(action.old), action.pos + len(action.old)],
            )

        else:
            assert 0

        self.closeList()

        if self.update_handler and self.update_handler(update_info) == False:
            return

        self.undo_list = self.undo_list[:-1]
        self.redo_list.append(action)

        self.text = update_info.text
        self.selection = update_info.selection
        self.makeVisible(self.selection[1])
        self.paint()

    ## \~japanese
    # 取り消した編集を再実行します。更新ハンドラは拒否できます。戻り値None。
    # \~english
    # Redo an undone edit; the update handler may reject it. Return None.
    # \~
    def redo(self):
        if len(self.redo_list) == 0:
            return

        action = self.redo_list[-1]

        if isinstance(action, action_Insert):
            update_info = EditWidget.UpdateInfo(
                self.text[: action.pos] + action.text + self.text[action.pos :],
                [action.pos + len(action.text), action.pos + len(action.text)],
            )

        elif isinstance(action, action_Delete) or isinstance(action, action_Back):  # noqa: SIM101  # Retain short-circuit evaluation; excluded from cleanup for performance.
            update_info = EditWidget.UpdateInfo(
                self.text[: action.pos] + self.text[action.pos + len(action.text) :],
                [action.pos, action.pos],
            )

        elif isinstance(action, action_Replace):
            update_info = EditWidget.UpdateInfo(
                self.text[: action.pos]
                + action.new
                + self.text[action.pos + len(action.old) :],
                [action.pos + len(action.new), action.pos + len(action.new)],
            )

        else:
            assert 0

        self.closeList()

        if self.update_handler and self.update_handler(update_info) == False:
            return

        self.undo_list.append(action)
        self.redo_list = self.redo_list[:-1]

        self.text = update_info.text
        self.selection = update_info.selection
        self.makeVisible(self.selection[1])
        self.paint()

    ## \~japanese
    # 親から仮想キーvk・MODKEY_*のmodを配送します。処理したキーはTrueを返す経路があります。未処理はNone。
    # \~english
    # Route a virtual key vk and MODKEY_* mod from the parent. Some handled paths return True; unhandled keys return None.
    # \~
    def onKeyDown(self, vk, mod):

        if mod == MODKEY_SHIFT:
            if vk in (self.vk_complete):
                if self.candidate_handler and self.list_window:
                    self.window.removeKeyMessage()
                    if self.list_window.numItems() == 0:
                        self.insertText("")
                        return True
                    return self.list_window.onKeyDown(vk, mod)

            elif vk == VK_LEFT:
                self.closeList()
                self.appendUndo(None)
                self.selection[1] = max(self.selection[1] - 1, 0)
            elif vk == VK_RIGHT:
                self.closeList()
                self.appendUndo(None)
                self.selection[1] = min(self.selection[1] + 1, len(self.text))
            elif vk == VK_HOME:
                self.closeList()
                self.appendUndo(None)
                self.selection[1] = 0
            elif vk == VK_END:
                self.closeList()
                self.appendUndo(None)
                self.selection[1] = len(self.text)
            self.makeVisible(self.selection[1])
            self.paint()

        elif mod == MODKEY_CTRL:
            if vk == VK_LEFT:
                self.closeList()
                self.appendUndo(None)
                new_cursor_pos = self.word_break_handler(
                    self.text, self.selection[1], -1
                )
                self.selection = [new_cursor_pos, new_cursor_pos]
                self.makeVisible(self.selection[1])
                self.paint()

            elif vk == VK_RIGHT:
                self.closeList()
                self.appendUndo(None)
                new_cursor_pos = self.word_break_handler(
                    self.text, self.selection[1], +1
                )
                self.selection = [new_cursor_pos, new_cursor_pos]
                self.makeVisible(self.selection[1])
                self.paint()

            elif vk == VK_BACK:
                if self.selection[0] == self.selection[1] and self.selection[0] > 0:
                    selection_left = self.word_break_handler(
                        self.text, self.selection[1], -1
                    )
                    selection_right = self.selection[1]
                    update_info = EditWidget.UpdateInfo(
                        self.text[:selection_left] + self.text[selection_right:],
                        [selection_left, selection_left],
                    )
                else:
                    selection_left = min(self.selection[0], self.selection[1])
                    selection_right = max(self.selection[0], self.selection[1])
                    update_info = EditWidget.UpdateInfo(
                        self.text[:selection_left] + self.text[selection_right:],
                        [selection_left, selection_left],
                    )

                if self.candidate_handler:
                    self.popupListPrepare(update_info, False)

                if self.update_handler and self.update_handler(update_info) == False:
                    return

                self.appendUndo(
                    action_Delete(
                        update_info.selection[0],
                        self.text[selection_left:selection_right],
                    )
                )
                self.appendUndo(None)

                self.text = update_info.text
                self.selection = update_info.selection
                self.makeVisible(self.selection[1])
                self.paint()

                if self.candidate_handler:
                    self.popupList()

            elif vk == VK_A:
                self.closeList()
                self.appendUndo(None)
                self.selection = [0, len(self.text)]
                self.makeVisible(self.selection[1])
                self.paint()

            elif vk == VK_X:
                self.appendUndo(None)
                if self.selection[0] == self.selection[1]:
                    return

                selection_left = min(self.selection[0], self.selection[1])
                selection_right = max(self.selection[0], self.selection[1])

                update_info = EditWidget.UpdateInfo(
                    self.text[:selection_left] + self.text[selection_right:],
                    [selection_left, selection_left],
                )

                self.closeList()

                if self.update_handler and self.update_handler(update_info) == False:
                    return

                self.appendUndo(
                    action_Delete(
                        selection_left, self.text[selection_left:selection_right]
                    )
                )
                self.appendUndo(None)

                ckit_misc.setClipboardText(self.text[selection_left:selection_right])

                self.text = update_info.text
                self.selection = update_info.selection
                self.makeVisible(self.selection[1])
                self.paint()

            elif vk == VK_C:
                self.appendUndo(None)
                if self.selection[0] == self.selection[1]:
                    return

                selection_left = min(self.selection[0], self.selection[1])
                selection_right = max(self.selection[0], self.selection[1])

                update_info = EditWidget.UpdateInfo(
                    self.text, [self.selection[1], self.selection[1]]
                )

                self.closeList()

                if self.update_handler and self.update_handler(update_info) == False:
                    return

                ckit_misc.setClipboardText(self.text[selection_left:selection_right])

                self.text = update_info.text
                self.selection = update_info.selection
                self.makeVisible(self.selection[1])
                self.paint()

            elif vk == VK_V:
                self.appendUndo(None)
                selection_left = min(self.selection[0], self.selection[1])
                selection_right = max(self.selection[0], self.selection[1])

                clipboard_text = ckit_misc.getClipboardText()

                update_info = EditWidget.UpdateInfo(
                    self.text[:selection_left]
                    + clipboard_text
                    + self.text[selection_right:],
                    [
                        selection_left + len(clipboard_text),
                        selection_left + len(clipboard_text),
                    ],
                )

                self.closeList()

                if self.update_handler and self.update_handler(update_info) == False:
                    return

                self.appendUndo(action_Insert(selection_left, clipboard_text))
                self.appendUndo(None)

                self.text = update_info.text
                self.selection = update_info.selection
                self.makeVisible(self.selection[1])
                self.paint()

            elif vk == VK_Z:
                self.appendUndo(None)
                self.undo()

            elif vk == VK_Y:
                self.redo()

            elif vk == VK_H:
                self.backSpace()

            elif vk == VK_K:
                self.removeCandidate()

        elif mod == MODKEY_SHIFT | MODKEY_CTRL:
            if vk == VK_LEFT:
                self.closeList()
                self.appendUndo(None)
                self.selection[1] = self.word_break_handler(
                    self.text, self.selection[1], -1
                )
                self.makeVisible(self.selection[1])
                self.paint()

            elif vk == VK_RIGHT:
                self.closeList()
                self.appendUndo(None)
                self.selection[1] = self.word_break_handler(
                    self.text, self.selection[1], +1
                )
                self.makeVisible(self.selection[1])
                self.paint()

        elif mod == 0:
            if vk in self.vk_complete or vk in (VK_UP, VK_DOWN, VK_PRIOR, VK_NEXT):
                if self.candidate_handler and self.list_window:
                    self.window.removeKeyMessage()
                    if self.list_window.numItems() == 0:
                        self.insertText("")
                        return True
                    return self.list_window.onKeyDown(vk, mod)

            elif vk == VK_TAB:
                if self.candidate_handler:
                    self.window.removeKeyMessage()

                    update_info = EditWidget.UpdateInfo(self.text, self.selection)

                    candidate_list, base_len = self.candidate_handler(update_info)

                    if len(candidate_list) > 0:
                        common_prefix = candidate_list[0].lower()
                        for item in candidate_list:
                            item_lower = item.lower()
                            while 1:
                                if item_lower.startswith(common_prefix):
                                    break
                                common_prefix = common_prefix[:-1]
                                if not common_prefix:
                                    break
                            if not common_prefix:
                                break

                        # Preserve the first candidate's letter case in the common prefix.
                        common_prefix_case = candidate_list[0][: len(common_prefix)]

                        selection_left = min(self.selection[0], self.selection[1])
                        selection_right = max(self.selection[0], self.selection[1])

                        undo_action = None

                        if (
                            self.text[base_len : base_len + len(common_prefix)].lower()
                            == common_prefix
                        ):
                            # The text already contains the common prefix; only adjust the selection.
                            new_selection_left = base_len + len(common_prefix)
                            update_info = EditWidget.UpdateInfo(
                                self.text,
                                [
                                    new_selection_left,
                                    max(new_selection_left, selection_right),
                                ],
                            )

                        else:
                            # Insert the common prefix when it is not already in the text.
                            left = self.text[:base_len]
                            mid = common_prefix_case
                            right = self.text[selection_right:]
                            update_info = EditWidget.UpdateInfo(
                                left + mid + right,
                                [len(left) + len(mid), len(left) + len(mid)],
                            )

                            undo_action = action_Replace(
                                base_len,
                                self.text[base_len:selection_right],
                                common_prefix_case,
                            )

                        if self.update_handler and self.update_handler(update_info) == False:
                            return

                        if undo_action:
                            self.appendUndo(undo_action)

                        self.text = update_info.text
                        self.selection = update_info.selection

                        self.insertText("")

                        return True

            elif vk == VK_ESCAPE:
                if self.candidate_handler and self.list_window and self.list_window.numItems() > 0:
                    self.closeList()
                    return True

            elif self.selection[0] == self.selection[1]:
                if vk == VK_LEFT:
                    self.closeList()
                    self.appendUndo(None)
                    new_cursor_pos = max(self.selection[1] - 1, 0)
                    self.selection = [new_cursor_pos, new_cursor_pos]
                elif vk == VK_RIGHT:
                    self.closeList()
                    self.appendUndo(None)
                    new_cursor_pos = min(self.selection[1] + 1, len(self.text))
                    self.selection = [new_cursor_pos, new_cursor_pos]
                elif vk == VK_HOME:
                    self.closeList()
                    self.appendUndo(None)
                    self.selection = [0, 0]
                elif vk == VK_END:
                    self.closeList()
                    self.appendUndo(None)
                    self.selection = [len(self.text), len(self.text)]
                elif vk == VK_DELETE:
                    update_info = EditWidget.UpdateInfo(
                        self.text[: self.selection[0]]
                        + self.text[self.selection[1] + 1 :],
                        [self.selection[0], self.selection[0]],
                    )

                    self.closeList()

                    if self.update_handler and self.update_handler(update_info) == False:
                        return

                    if isinstance(self.last_action, action_Delete):
                        self.last_action.text += self.text[
                            self.selection[0] : self.selection[0] + 1
                        ]
                    else:
                        self.appendUndo(
                            action_Delete(
                                self.selection[0],
                                self.text[self.selection[0] : self.selection[0] + 1],
                            )
                        )

                    self.text = update_info.text
                    self.selection = update_info.selection
                elif vk == VK_BACK:
                    self.backSpace()
                    return True
                self.makeVisible(self.selection[1])
                self.paint()
            else:
                if vk == VK_LEFT:
                    self.closeList()
                    self.appendUndo(None)
                    new_cursor_pos = min(self.selection[0], self.selection[1])
                    self.selection = [new_cursor_pos, new_cursor_pos]
                elif vk == VK_RIGHT:
                    self.closeList()
                    self.appendUndo(None)
                    new_cursor_pos = max(self.selection[0], self.selection[1])
                    self.selection = [new_cursor_pos, new_cursor_pos]
                elif vk == VK_HOME:
                    self.closeList()
                    self.appendUndo(None)
                    self.selection = [0, 0]
                elif vk == VK_END:
                    self.closeList()
                    self.appendUndo(None)
                    self.selection = [len(self.text), len(self.text)]
                elif vk == VK_DELETE or vk == VK_BACK:
                    selection_left = min(self.selection[0], self.selection[1])
                    selection_right = max(self.selection[0], self.selection[1])
                    update_info = EditWidget.UpdateInfo(
                        self.text[:selection_left] + self.text[selection_right:],
                        [selection_left, selection_left],
                    )

                    self.closeList()

                    if self.update_handler and self.update_handler(update_info) == False:
                        return
                    self.appendUndo(
                        action_Delete(
                            selection_left, self.text[selection_left:selection_right]
                        )
                    )
                    self.appendUndo(None)
                    self.text = update_info.text
                    self.selection = update_info.selection
                self.makeVisible(self.selection[1])
                self.paint()

    ## \~japanese
    # 親から文字コードchとMODKEY_*のmodを配送します。戻り値は編集成否の判定に使いません。
    # \~english
    # Route a character code ch and MODKEY_* mod from the parent; do not use the return value to determine edit success.
    # \~
    def onChar(self, ch, mod):

        if self.autofix_list:
            for autofix_string in self.autofix_list:
                if chr(ch) in autofix_string:
                    selection_left = min(self.selection[0], self.selection[1])
                    selection_right = max(self.selection[0], self.selection[1])

                    min_pos = -1
                    for autofix_char in autofix_string:
                        pos = self.text.find(
                            autofix_char, selection_left, selection_right
                        )
                        if pos >= 0 and (min_pos < 0 or pos < min_pos):
                            min_pos = pos

                    if min_pos >= 0:
                        self.selection = [min_pos, selection_right]
                    else:
                        self.selection = [selection_right, selection_right]

        if ch <= 0xFF and (ch < 0x20 or ch == 0x7F):
            return
        else:
            self.insertText(chr(ch))

    ## \~japanese
    # 親の活性化状態を配送します。候補窓があれば再描画します。active引数は現在参照しません。
    # \~english
    # Route parent activation and repaint an existing candidate window; active is currently unused.
    # \~
    def onWindowActivate(self, active):
        if self.list_window:
            self.list_window.paint()

    ## \~japanese
    # 親の移動時に候補を閉じます。位置を再計算して開き直す操作ではありません。
    # \~english
    # Close candidates when the parent moves; do not reposition/reopen them.
    # \~
    def onWindowMove(self):
        self.closeList()

    ## \~japanese
    # 候補を準備します。update_info=Noneなら現在値。completeが真なら候補をupdate_infoへ反映し、expectedは初期候補の選択基準です。戻り値None。
    # \~english
    # Prepare candidates; update_info=None uses current values. True complete applies a candidate to update_info; expected determines initial selection. Return None.
    # \~
    def popupListPrepare(self, update_info=None, complete: int = True, expected=None):
        if self.candidate_handler:
            if update_info is None:
                update_info = EditWidget.UpdateInfo(self.text, self.selection)

            if expected is None:
                expected = EditWidget.UpdateInfo(self.text, self.selection)

            selection_right = max(update_info.selection[0], update_info.selection[1])

            candidate_list, base_len = self.candidate_handler(update_info)

            if complete:
                expected_candidate = expected.text[
                    base_len : max(expected.selection[0], expected.selection[1])
                ]
                try:
                    select = candidate_list.index(expected_candidate)
                except ValueError:
                    select = 0
            else:
                select = -1

            if complete and len(candidate_list) > 0:
                left = update_info.text[:base_len]
                mid = candidate_list[select]
                right = update_info.text[selection_right:]

                update_info.text = left + mid + right
                update_info.selection = [update_info.selection[0], len(left) + len(mid)]

            self.list_window_prepared_info = [candidate_list, base_len, select]

    ## \~japanese
    # 準備済み候補を表示します。先にpopupListPrepareが必要で、未準備ならTypeErrorです。位置変更時は旧窓を50ms後に破棄します。
    # \~english
    # Show prepared candidates; call popupListPrepare first or receive TypeError. Geometry changes destroy the old window after 50 ms.
    # \~
    def popupList(self):
        if self.candidate_handler and self.list_window:
            prepared_info = self.list_window_prepared_info
            if prepared_info is None:
                raise TypeError("cannot unpack non-iterable NoneType object")
            candidate_list, base_len, select = prepared_info

            text = self.alternateText(self.text)
            x, y1 = self.window.charToScreen(
                self.x + self.window.getStringWidth(text[:base_len]) - self.scroll_pos,
                self.y,
            )
            x, y2 = self.window.charToScreen(
                self.x + self.window.getStringWidth(text[:base_len]) - self.scroll_pos,
                self.y + 1,
            )

            # Prepare the candidate window geometry; replace the window if it changes to avoid flicker.
            new_list_window_possize_info = [
                x,
                y1,
                y2,
                min(len(candidate_list), EditWidget.candidate_list_max_height),
            ]
            if self.list_window_possize_info != new_list_window_possize_info:
                old_list_window = self.list_window
                old_enabled = old_list_window.isEnabled()
                old_base_len = self.list_window_base_len
                old_possize_info = self.list_window_possize_info
                new_list_window: CandidateWindow | None = None
                replacement_pending = True
                destroy_requested = False

                def delayedDestroy():
                    nonlocal destroy_requested
                    destroy_requested = True
                    if not replacement_pending:
                        old_list_window.destroy()

                def restoreState():
                    self.list_window = old_list_window
                    self.list_window_base_len = old_base_len
                    self.list_window_possize_info = old_possize_info

                def destroyNewWindow():
                    if new_list_window is not None:
                        new_list_window.destroy()

                with (
                    ckit_misc._cleanup_on_exit(old_list_window.enable, old_enabled, error_only=True),
                    ckit_misc._cleanup_on_exit(destroyNewWindow, error_only=True),
                    ckit_misc._cleanup_on_exit(restoreState, error_only=True),
                ):
                    self.list_window_base_len = base_len
                    old_list_window.enable(False)
                    new_list_window = self.createCandidateWindow()
                    self.list_window = new_list_window
                    self.window.delayedCall(delayedDestroy, 50)
                    self.list_window_possize_info = new_list_window_possize_info
                    self.list_window.setItems(x, y1, y2, candidate_list, select)
                replacement_pending = False
                if destroy_requested:
                    delayedDestroy()

            else:
                old_base_len = self.list_window_base_len
                with ckit_misc._cleanup_on_exit(
                    setattr, self, "list_window_base_len", old_base_len, error_only=True
                ):
                    self.list_window_base_len = base_len
                    self.list_window.setItems(x, y1, y2, candidate_list, select)

        self.list_window_prepared_info = None

    ## \~japanese
    # 候補窓がなければNone、あれば項目数が0以外かのboolを返します。
    # \~english
    # Return None when there is no completion window, otherwise whether its item count is nonzero.
    # \~
    def isListOpened(self):
        return self.list_window and self.list_window.numItems() != 0

    ## \~japanese
    # 候補ハンドラと窓があれば項目を空にします。窓の破棄はdestroyで行います。
    # \~english
    # Clear completion items when a handler and window exist; destroy releases the window.
    # \~
    def closeList(self):
        if self.candidate_handler and self.list_window:
            x, y = self.window.charToScreen(0, 0)
            self.list_window_base_len = 0
            self.list_window_possize_info = None
            self.list_window.setItems(x, y, y, [], 0)

    def onListSelChange(self, select, text):
        selection_left = min(self.selection[0], self.selection[1])
        selection_right = max(self.selection[0], self.selection[1])

        left = self.text[: self.list_window_base_len]
        mid = text
        right = self.text[selection_right:]

        update_info = EditWidget.UpdateInfo(
            left + mid + right, [selection_left, len(left) + len(mid)]
        )

        if self.update_handler and self.update_handler(update_info) == False:
            return

        old = self.text[self.list_window_base_len : selection_right]
        new = text
        if old != new:
            self.appendUndo(action_Replace(self.list_window_base_len, old, new))

        self.text = update_info.text
        self.selection = update_info.selection
        self.makeVisible(self.selection[1])
        self.paint()

    ## \~japanese
    # 現在の全テキストを削除ハンドラへ渡します。成功なら選択候補を除去（一覧なしならclear）してTrue、それ以外はFalse。
    # \~english
    # Pass current full text to the removal handler; on success remove the selected candidate (or clear when no list) and return True, else False.
    # \~
    def removeCandidate(self):
        if self.candidate_remove_handler:
            if not self.candidate_remove_handler(self.text):
                return False
            if self.isListOpened() and self.list_window:
                selection = self.list_window.getSelection()
                self.list_window.remove(selection)
            else:
                self.clear()
            return True
        return False

    ## \~japanese
    # 現在の選択をtextで置換します。候補・更新ハンドラ、Undo、スクロール、描画を処理します。戻り値None。
    # \~english
    # Replace the selection with text, processing completion/update callbacks, undo, scrolling and painting. Return None.
    # \~
    def insertText(self, text):
        selection_left = min(self.selection[0], self.selection[1])
        selection_right = max(self.selection[0], self.selection[1])

        new_cursor_pos = selection_left + len(text)
        update_info = EditWidget.UpdateInfo(
            self.text[:selection_left] + text + self.text[selection_right:],
            [new_cursor_pos, new_cursor_pos],
        )

        if self.candidate_handler:
            self.popupListPrepare(update_info, self.auto_complete)

        if self.update_handler and self.update_handler(update_info) == False:
            return

        inserted_text = (
            text
            + update_info.text[
                update_info.selectionLeft() : update_info.selectionRight()
            ]
        )

        if selection_left == selection_right:
            if isinstance(self.last_action, action_Insert):
                self.last_action.text += inserted_text
            else:
                if inserted_text:
                    self.appendUndo(action_Insert(selection_left, inserted_text))
        else:
            old = self.text[selection_left:selection_right]
            new = inserted_text
            if old != new:
                self.appendUndo(action_Replace(selection_left, old, new))

        self.text = update_info.text
        self.selection = update_info.selection
        self.makeVisible(self.selection[1])
        self.paint()

        if self.candidate_handler:
            self.popupList()

    ## \~japanese
    # cursorの直前1文字を削除します。選択範囲全体の削除ではありません。更新ハンドラ・Undo・描画を処理します。
    # \~english
    # Delete one character before the cursor, rather than the entire selection. Process update callback, undo and painting.
    # \~
    def backSpace(self):
        remove_left = max(self.selection[1] - 1, 0)
        update_info = EditWidget.UpdateInfo(
            self.text[:remove_left] + self.text[self.selection[1] :],
            [remove_left, remove_left],
        )

        self.closeList()

        if self.update_handler and self.update_handler(update_info) == False:
            return

        if isinstance(self.last_action, action_Back):
            self.last_action.text = (
                self.text[remove_left : self.selection[1]] + self.last_action.text
            )
            self.last_action.pos -= 1
        else:
            self.appendUndo(
                action_Back(remove_left, self.text[remove_left : self.selection[1]])
            )

        self.text = update_info.text
        self.selection = update_info.selection
        self.makeVisible(self.selection[1])
        self.paint()

    ## \~japanese
    # 全テキストを選択して再描画します。更新ハンドラは呼びません。
    # \~english
    # Select all text and repaint without calling the update handler.
    # \~
    def selectAll(self):
        self.selection = [0, len(self.text)]
        self.paint()

    ## \~japanese
    # 全テキストを空へ更新します。更新ハンドラで拒否・変更できます。Undoへ記録し再描画します。
    # \~english
    # Propose empty text; the update handler may reject or modify it. Record undo and repaint.
    # \~
    def clear(self):
        update_info = EditWidget.UpdateInfo("", [0, 0])

        if self.update_handler and self.update_handler(update_info) == False:
            return

        self.appendUndo(action_Delete(0, self.text))
        self.appendUndo(None)

        self.text = update_info.text
        self.selection = update_info.selection
        self.makeVisible(self.selection[1])
        self.paint()

    ## \~japanese
    # 文字位置posが見えるよう横スクロールを計算します。再描画しません。
    # \~english
    # Compute horizontal scrolling to reveal character position pos without repainting.
    # \~
    def makeVisible(self, pos):
        def countStringWidthRight(text, pos, width):
            while True:
                if pos < 0 or pos > len(text) - 1:
                    width -= 1
                else:
                    width -= self.window.getStringWidth(text[pos])
                if width < 0:
                    break
                pos += 1
            return pos

        def countStringWidthLeft(text, pos, width):
            while True:
                pos -= 1
                if pos < 0 or pos > len(text) - 1:
                    width -= 1
                else:
                    width -= self.window.getStringWidth(text[pos])
                if width < 0:
                    break
            return pos + 1

        if pos < countStringWidthRight(
            self.text, self.scroll_pos + 1, self.margin1 - 1
        ):
            # Scroll left.
            self.scroll_pos = max(
                countStringWidthLeft(self.text, pos, self.margin2), -self.margin1
            )
        elif pos > countStringWidthRight(
            self.text, self.scroll_pos, self.width - self.margin1
        ):
            # Scroll right.
            pos1 = countStringWidthLeft(self.text, pos, self.width - self.margin2)
            pos2 = countStringWidthLeft(
                self.text, len(self.text), self.width - self.margin1
            )
            self.scroll_pos = min(pos1, pos2)
        elif self.isScrolled() and len(self.text) < countStringWidthRight(
            self.text, self.scroll_pos, self.width - self.margin1
        ):
            # Scroll left to avoid excessive blank space on the right.
            pos1 = countStringWidthLeft(self.text, pos, self.width - self.margin2)
            pos2 = countStringWidthLeft(
                self.text, len(self.text), self.width - self.margin1
            )
            self.scroll_pos = min(pos1, pos2)
            self.scroll_pos = max(self.scroll_pos, -self.margin1)

        assert self.scroll_pos >= -self.margin1

    ## \~japanese
    # 表示用にtextのタブを空白へ置換した新しい文字列を返します。保存テキストは変更しません。派生実装で表示変換を差し替えられます。
    # \~english
    # Return a new display string with tabs replaced by spaces; stored text is unchanged. Override to customize display conversion.
    # \~
    def alternateText(self, text):
        return text.replace("\t", " ")

    ## \~japanese
    # 現在状態を親へ描画します。戻り値None。親の描画・フォーカス更新から呼びます。
    # \~english
    # Paint current state into the parent; return None. Call from host painting/focus updates.
    # \~
    def paint(self):
        selection_left = min(self.selection[0], self.selection[1])
        selection_right = max(self.selection[0], self.selection[1])

        x = self.x
        width = self.width

        fg_color = ckit_theme.getColor("fg")
        bg_color = ckit_theme.getColor("bg")
        if fg_color is None or bg_color is None:
            raise TypeError("'NoneType' object is not iterable")
        line_color = tuple((fg + bg) // 2 for fg, bg in zip(fg_color, bg_color))
        line = None if self.no_bg else (LINE_BOTTOM, line_color)
        attribute_edit = ckitcore.Attribute(
            fg=ckit_theme.getColor("fg"), bg=ckit_theme.getColor("bg"), line0=line
        )
        attribute_edit_selected = ckitcore.Attribute(
            fg=ckit_theme.getColor("select_fg"),
            bg=ckit_theme.getColor("select_bg"),
            line0=line,
        )

        self.window.putString(x, self.y, width, 1, attribute_edit, " " * width)

        text = self.alternateText(self.text)

        if self.scroll_pos < selection_left:
            if self.scroll_pos < 0:
                left_string = text[0:selection_left]
                x += 1
                width -= 1
            else:
                left_string = text[self.scroll_pos : selection_left]

            self.window.putString(x, self.y, width, 1, attribute_edit, left_string)
            left_string_width = self.window.getStringWidth(left_string)
            x += left_string_width
            width -= left_string_width

        if selection_left < selection_right:
            if self.scroll_pos < selection_left:
                mid_string = text[selection_left:selection_right]
            else:
                mid_string = text[self.scroll_pos : selection_right]

            if self.enable_cursor:
                attr = attribute_edit_selected
            else:
                attr = attribute_edit

            self.window.putString(x, self.y, width, 1, attr, mid_string)
            mid_string_width = self.window.getStringWidth(mid_string)
            x += mid_string_width
            width -= mid_string_width

        if selection_right < self.scroll_pos + self.width:
            right_string = text[selection_right:]

            self.window.putString(x, self.y, width, 1, attribute_edit, right_string)
            right_string_width = self.window.getStringWidth(right_string)
            x += right_string_width
            width -= right_string_width

        if self.enable_cursor:
            if self.scroll_pos < 0:
                left_string = text[0 : self.selection[1]]
                offset = 1
            else:
                left_string = text[self.scroll_pos : self.selection[1]]
                offset = 0
            left_string_width = self.window.getStringWidth(left_string)
            self.window.setCursorPos(self.x + offset + left_string_width, self.y)

    ## \~japanese
    # 現在の文字列を返します。
    # \~english
    # Return the current string.
    # \~
    def getText(self):
        return self.text

    ## \~japanese
    # 文字列だけを設定します。選択・Undo・更新通知・候補・スクロール・描画は更新しません。必要なら別途処理します。
    # \~english
    # Assign text only. Manage selection, undo, update notification, candidates, scrolling and repaint separately.
    # \~
    def setText(self, text):
        self.text = text

    ## \~japanese
    # [anchor, cursor]を内部リストのまま返します。独立した保存値が必要ならコピーします。
    # \~english
    # Return the internal [anchor, cursor] list; copy it for an independent snapshot.
    # \~
    def getSelection(self):
        return self.selection

    ## \~japanese
    # [anchor, cursor]をコピーせず保持します。範囲補正・通知・スクロール・描画は行いません。
    # \~english
    # Retain [anchor, cursor] without copying, clamping, notifying, scrolling or repainting.
    # \~
    def setSelection(self, selection):
        self.selection = selection

    ## \~japanese
    # 横スクロールが初期位置と異なればTrueを返します。
    # \~english
    # Return True when horizontal scrolling differs from the initial position.
    # \~
    def isScrolled(self):
        return self.scroll_pos != -self.margin1


class CandidateWindow(ckit_textwindow.TextWindow):
    def __init__(
        self,
        x,
        y,
        min_width,
        min_height,
        max_width,
        max_height,
        parent_window,
        keydown_hook=None,
        selchange_handler=None,
    ):
        bg = ckit_theme.getColor("bg")
        fg = ckit_theme.getColor("fg")
        bg = ckit_theme._require_rgb(bg)
        fg = ckit_theme._require_rgb(fg)

        frame_color = (
            (bg[0] + fg[0]) // 2,
            (bg[1] + fg[1]) // 2,
            (bg[2] + fg[2]) // 2,
        )

        ckit_textwindow.TextWindow.__init__(
            self,
            x=x,
            y=y,
            width=5,
            height=5,
            origin=ORIGIN_X_LEFT | ORIGIN_Y_TOP,
            parent_window=parent_window,
            bg_color=ckit_theme.getColor("bg"),
            caret0_color=ckit_theme.getColor("caret0"),
            caret1_color=ckit_theme.getColor("caret1"),
            frame_color=frame_color,
            border_size=0,
            transparency=255,  # Use WS_EX_LAYERED to avoid flicker.
            show=False,
            resizable=False,
            title_bar=False,
            minimizebox=False,
            maximizebox=False,
            activate_handler=self.onActivate,
            keydown_handler=self.onKeyDown,
            char_handler=self.onChar,
            ncpaint=True,
        )

        with ckit_misc._cleanup_on_exit(ckit_textwindow.TextWindow.destroy, self, error_only=True):
            self.parent_window = parent_window

            self.min_width = min_width
            self.min_height = min_height
            self.max_width = max_width
            self.max_height = max_height

            self.keydown_hook = keydown_hook
            self.selchange_handler = selchange_handler

            self.setItems(x, y, y, [], 0)

    def setItems(self, x, y1, y2, items, select=0):
        # Adjust x to account for the window frame.
        char_x, _char_y = self.charToScreen(0, 0)
        window_rect = self.getWindowRect()
        x -= char_x - window_rect[0]

        max_item_width = 0
        for item in items:
            if isinstance(item, list) or isinstance(item, tuple):  # noqa: SIM101  # Retain short-circuit evaluation; excluded from cleanup for performance.
                item = item[0]
            item_width = self.getStringWidth(item)
            if item_width > max_item_width:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
                max_item_width = item_width

        window_width = max_item_width
        window_height = len(items)

        window_width = max(window_width, self.min_width)
        window_height = max(window_height, self.min_height)

        window_width = min(window_width, self.max_width)
        window_height = min(window_height, self.max_height)

        # Place the window above if it does not fit below in the work area.
        y = y2
        monitor_info_list = pyauto.Window.getMonitorInfo()
        for monitor_info in monitor_info_list:
            if (
                monitor_info[0][0] <= x < monitor_info[0][2]
                and monitor_info[0][1] <= y1 < monitor_info[0][3]
            ):
                window_rect = self.getWindowRect()
                _char_w, char_h = self.getCharSize()
                if (
                    y2
                    + (window_rect[3] - window_rect[1])
                    + (self.max_height - self.height()) * char_h
                    >= monitor_info[1][3]
                ):
                    y = y1 - (
                        (window_rect[3] - window_rect[1])
                        + (window_height - self.height()) * char_h
                    )
                break

        if not len(items):
            self.show(False, False)

        self.setPosSize(
            x=x,
            y=y,
            width=window_width,
            height=window_height,
            origin=ORIGIN_X_LEFT | ORIGIN_Y_TOP,
        )

        self.items = items
        self.scroll_info = ckit_misc.ScrollInfo()
        self.select = select
        self.scroll_info.makeVisible(self.select, self.height())

        self.paint()

        if len(items):
            self.show(True, False)

    def remove(self, index):
        del self.items[index]

        if self.select > index:
            self.select -= 1

        if not len(self.items):
            self.select = -1
            self.show(False, False)
            return

        if self.select < 0:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
            self.select = 0
        if self.select > len(self.items) - 1:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
            self.select = len(self.items) - 1

        if self.selchange_handler:
            self.selchange_handler(self.select, self.items[self.select])

        self.paint()

    def onActivate(self, active):
        if active:
            self.parent_window.activate()

    def onKeyDown(self, vk, mod):
        if self.keydown_hook and self.keydown_hook(vk, mod):
            return True

        if mod == MODKEY_SHIFT:
            if vk == VK_SPACE:
                if not len(self.items):
                    return True
                self.select -= 1
                if self.select < 0:
                    self.select = len(self.items) - 1
                self.scroll_info.makeVisible(self.select, self.height())

                if self.selchange_handler:
                    self.selchange_handler(self.select, self.items[self.select])

                self.paint()
                return True

        elif mod == 0:
            if vk == VK_SPACE:
                if not len(self.items):
                    return True
                self.select += 1
                if self.select > len(self.items) - 1:
                    self.select = 0
                self.scroll_info.makeVisible(self.select, self.height())

                if self.selchange_handler:
                    self.selchange_handler(self.select, self.items[self.select])

                self.paint()
                return True

            elif vk == VK_UP:
                if not len(self.items):
                    return True
                if self.select >= 0:
                    self.select -= 1
                    if self.select < 0:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
                        self.select = 0
                else:
                    self.select = len(self.items) - 1
                self.scroll_info.makeVisible(self.select, self.height())

                if self.selchange_handler:
                    self.selchange_handler(self.select, self.items[self.select])

                self.paint()
                return True

            elif vk == VK_DOWN:
                if not len(self.items):
                    return True
                self.select += 1
                if self.select > len(self.items) - 1:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
                    self.select = len(self.items) - 1
                self.scroll_info.makeVisible(self.select, self.height())

                if self.selchange_handler:
                    self.selchange_handler(self.select, self.items[self.select])

                self.paint()
                return True

            elif vk == VK_PRIOR:
                if not len(self.items):
                    return True

                if self.select >= 0:
                    if self.select > self.scroll_info.pos:
                        self.select = self.scroll_info.pos
                    else:
                        self.select -= self.height()
                        if self.select < 0:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
                            self.select = 0
                else:
                    self.select = len(self.items) - 1

                self.scroll_info.makeVisible(self.select, self.height())

                if self.selchange_handler:
                    self.selchange_handler(self.select, self.items[self.select])

                self.paint()
                return True

            elif vk == VK_NEXT:
                if not len(self.items):
                    return True
                if self.select < self.scroll_info.pos + self.height() - 1:
                    self.select = self.scroll_info.pos + self.height() - 1
                else:
                    self.select += self.height()
                if self.select > len(self.items) - 1:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
                    self.select = len(self.items) - 1
                self.scroll_info.makeVisible(self.select, self.height())

                if self.selchange_handler:
                    self.selchange_handler(self.select, self.items[self.select])

                self.paint()
                return True

    def onChar(self, ch, mod):
        pass

    def paint(self):
        x = 0
        y = 0
        width = self.width()
        height = self.height()

        attribute_normal = ckitcore.Attribute(fg=ckit_theme.getColor("fg"))
        attribute_candidate = ckitcore.Attribute(
            fg=ckit_theme.getColor("fg"), bg=ckit_theme.getColor("bg")
        )
        attribute_candidate_selected = ckitcore.Attribute(
            fg=ckit_theme.getColor("select_fg"), bg=ckit_theme.getColor("select_bg")
        )

        active = self.parent_window.isActive()

        for i in range(height):
            index = self.scroll_info.pos + i
            if index < len(self.items):
                item = self.items[index]
                if isinstance(item, list) or isinstance(item, tuple):  # noqa: SIM101  # Retain short-circuit evaluation; excluded from cleanup for performance.
                    item = item[0]

                if active and self.select == index:
                    attr = attribute_candidate_selected
                else:
                    attr = attribute_candidate
                self.putString(x, y + i, width, 1, attr, " " * width)
                self.putString(x, y + i, width, 1, attr, item)
            else:
                self.putString(x, y + i, width, 1, attribute_normal, " " * width)

    def getSelection(self):
        return self.select

    def numItems(self):
        return len(self.items)


# ----------------------------------------------------------------------------------------------------------------------------
#
# ----------------------------------------------------------------------------------------------------------------------------


## \~japanese
# 日時編集ウィジェット
# 
#
# timestampは(年, 月, 日, 時, 分, 秒)の整数シーケンスです。固定22×1セルで構築します。
# 左右キーで項目を切り替え、数字を入力します。移動先は全選択し、年の左端・秒の右端では移動も選択変更もしません。
# 編集中は年・月・日の0や一時的に存在しない日付も許容します。
# 初期値とgetValueは年1〜9999・暦日（うるう年を含む）・時0〜23・分秒0〜59を検証し、不正値はValueErrorです。
# getValueは有効な6整数のタプルを返し、不正値を補正しません。確定前に呼び、失敗時は入力を続けられるようにします。
# setPosSizeはwidth/heightにかかわらず22×1セルで6欄を移動します。showは内部欄にも反映し、destroyで全欄を解放します。
#
# \~english
# Date and time editor widget
# 
#
# timestamp is an integer sequence (year, month, day, hour, minute, second). Construction uses a fixed 22 by 1 cell area.
# Left/Right switch fields and select the destination in full; type digits to edit. Left at year and Right at second keep focus and selection.
# Zero year/month/day and temporarily invalid dates are allowed during editing.
# Initial values and getValue validate years 1..9999, calendar dates including leap years, hours 0..23 and minutes/seconds 0..59; invalid values raise ValueError.
# getValue returns six valid integers without correcting invalid dates. Call it before accepting and allow continued editing on failure.
# setPosSize moves all six fields in a fixed 22 by 1 cell area regardless of width/height. show propagates visibility; destroy releases all fields.
#
# \~
class TimeWidget(Widget):
    FOCUS_YEAR = 0
    FOCUS_MONTH = 1
    FOCUS_DAY = 2
    FOCUS_HOUR = 3
    FOCUS_MINUTE = 4
    FOCUS_SECOND = 5

    ## \~japanese
    # TimeWidgetを構築します。引数・所有資源はクラス説明を参照してください。
    # \~english
    # Construct TimeWidget; see the class description for arguments and owned resources.
    # \~
    def __init__(self, window, x, y, timestamp):
        Widget.__init__(self, window, x, y, 22, 1)

        year, month, day, hour, minute, second = timestamp
        _datetime.datetime(year, month, day, hour, minute, second)
        self.year_edit = self.month_edit = self.day_edit = None
        self.hour_edit = self.minute_edit = self.second_edit = None
        with _cleanup_on_exit(self.destroy, error_only=True):
            self.year_edit = EditWidget(
                window,
                x + 1,
                y,
                4,
                1,
                "%04d" % timestamp[0],  # noqa: UP031  # Preserve percent-d conversion for public values.
                None,
                0,
                1,
                no_bg=True,
                update_handler=self.onYearUpdate,
            )
            self.month_edit = EditWidget(
                window,
                x + 6,
                y,
                2,
                1,
                "%02d" % timestamp[1],  # noqa: UP031  # Preserve percent-d conversion for public values.
                None,
                0,
                1,
                no_bg=True,
                update_handler=self.onMonthUpdate,
            )
            self.day_edit = EditWidget(
                window,
                x + 9,
                y,
                2,
                1,
                "%02d" % timestamp[2],  # noqa: UP031  # Preserve percent-d conversion for public values.
                None,
                0,
                1,
                no_bg=True,
                update_handler=self.onDayUpdate,
            )
            self.hour_edit = EditWidget(
                window,
                x + 13,
                y,
                2,
                1,
                "%02d" % timestamp[3],  # noqa: UP031  # Preserve percent-d conversion for public values.
                None,
                0,
                1,
                no_bg=True,
                update_handler=self.onHourUpdate,
            )
            self.minute_edit = EditWidget(
                window,
                x + 16,
                y,
                2,
                1,
                "%02d" % timestamp[4],  # noqa: UP031  # Preserve percent-d conversion for public values.
                None,
                0,
                1,
                no_bg=True,
                update_handler=self.onMinuteUpdate,
            )
            self.second_edit = EditWidget(
                window,
                x + 19,
                y,
                2,
                1,
                "%02d" % timestamp[5],  # noqa: UP031  # Preserve percent-d conversion for public values.
                None,
                0,
                1,
                no_bg=True,
                update_handler=self.onSecondUpdate,
            )

            self.year_edit.enableIme(False)
            self.month_edit.enableIme(False)
            self.day_edit.enableIme(False)
            self.hour_edit.enableIme(False)
            self.minute_edit.enableIme(False)
            self.second_edit.enableIme(False)

            self.year_edit.selectAll()
            self.month_edit.selectAll()
            self.day_edit.selectAll()
            self.hour_edit.selectAll()
            self.minute_edit.selectAll()
            self.second_edit.selectAll()

            self.focus = TimeWidget.FOCUS_YEAR

            self.paint()

    ## \~japanese
    # 内部の6入力欄を解放します。繰返し呼出し可能。親は破棄しません。
    # \~english
    # Release the six nested edit controls; repeated calls are safe. Do not destroy the parent.
    # \~
    def destroy(self):
        with _ExitStack() as cleanup:
            for name in ("year_edit", "month_edit", "day_edit", "hour_edit", "minute_edit", "second_edit"):
                edit = getattr(self, name)
                if edit is not None:
                    setattr(self, name, None)
                    cleanup.enter_context(_cleanup_on_exit(edit.destroy))

    ## \~japanese
    # 可視状態を内部の6入力欄へ反映します。以前の描画は親から消去してください。
    # \~english
    # Apply visibility to all six nested controls; erase prior drawing from the parent.
    # \~
    def show(self, visible):
        Widget.show(self, visible)
        for edit in (self.year_edit, self.month_edit, self.day_edit, self.hour_edit, self.minute_edit, self.second_edit):
            _cast(EditWidget, edit).show(visible)

    ## \~japanese
    # 固定22×1セルのまま移動し、内部欄とIME矩形を再配置します。再描画しません。
    # \~english
    # Move the fixed 22 by 1 cell control, reposition nested fields and update IME rectangles without repainting.
    # \~
    def setPosSize(self, x, y, width, height):
        Widget.setPosSize(self, x, y, 22, 1)
        for edit, offset, size in ((self.year_edit, 1, 4), (self.month_edit, 6, 2),
                                   (self.day_edit, 9, 2), (self.hour_edit, 13, 2),
                                   (self.minute_edit, 16, 2), (self.second_edit, 19, 2)):
            _cast(EditWidget, edit).setPosSize(x + offset, y, size, 1)

    def onYearUpdate(self, info):
        if len(info.text.strip()) == 0:
            i = 0
        else:
            try:
                i = int(info.text)
            except ValueError:
                return False
        if not 0 <= i <= 9999:
            return False
        info.text = f"{i:04d}"
        info.selection = [4, 4]
        return True

    def onMonthUpdate(self, info):
        if len(info.text.strip()) == 0:
            i = 0
        else:
            try:
                i = int(info.text)
            except ValueError:
                return False
        if not 0 <= i <= 12:
            return False
        info.text = f"{i:02d}"
        info.selection = [2, 2]
        return True

    def onDayUpdate(self, info):
        if len(info.text.strip()) == 0:
            i = 0
        else:
            try:
                i = int(info.text)
            except ValueError:
                return False
        if not 0 <= i <= 31:
            return False
        info.text = f"{i:02d}"
        info.selection = [2, 2]
        return True

    def onHourUpdate(self, info):
        if len(info.text.strip()) == 0:
            i = 0
        else:
            try:
                i = int(info.text)
            except ValueError:
                return False
        if not 0 <= i <= 23:
            return False
        info.text = f"{i:02d}"
        info.selection = [2, 2]
        return True

    def onMinuteUpdate(self, info):
        if len(info.text.strip()) == 0:
            i = 0
        else:
            try:
                i = int(info.text)
            except ValueError:
                return False
        if not 0 <= i <= 59:
            return False
        info.text = f"{i:02d}"
        info.selection = [2, 2]
        return True

    def onSecondUpdate(self, info):
        if len(info.text.strip()) == 0:
            i = 0
        else:
            try:
                i = int(info.text)
            except ValueError:
                return False
        if not 0 <= i <= 59:
            return False
        info.text = f"{i:02d}"
        info.selection = [2, 2]
        return True

    ## \~japanese
    # 親から仮想キーvk・MODKEY_*のmodを配送します。戻り値None。
    # \~english
    # Route a virtual key vk and MODKEY_* mod from the parent. Return None.
    # \~
    def onKeyDown(self, vk, mod):

        if vk == VK_LEFT:
            if self.focus == TimeWidget.FOCUS_MONTH:
                self.focus = TimeWidget.FOCUS_YEAR
                _cast(EditWidget, self.year_edit).selectAll()
            elif self.focus == TimeWidget.FOCUS_DAY:
                self.focus = TimeWidget.FOCUS_MONTH
                _cast(EditWidget, self.month_edit).selectAll()
            elif self.focus == TimeWidget.FOCUS_HOUR:
                self.focus = TimeWidget.FOCUS_DAY
                _cast(EditWidget, self.day_edit).selectAll()
            elif self.focus == TimeWidget.FOCUS_MINUTE:
                self.focus = TimeWidget.FOCUS_HOUR
                _cast(EditWidget, self.hour_edit).selectAll()
            elif self.focus == TimeWidget.FOCUS_SECOND:
                self.focus = TimeWidget.FOCUS_MINUTE
                _cast(EditWidget, self.minute_edit).selectAll()
            self.paint()

        elif vk == VK_RIGHT:
            if self.focus == TimeWidget.FOCUS_YEAR:
                self.focus = TimeWidget.FOCUS_MONTH
                _cast(EditWidget, self.month_edit).selectAll()
            elif self.focus == TimeWidget.FOCUS_MONTH:
                self.focus = TimeWidget.FOCUS_DAY
                _cast(EditWidget, self.day_edit).selectAll()
            elif self.focus == TimeWidget.FOCUS_DAY:
                self.focus = TimeWidget.FOCUS_HOUR
                _cast(EditWidget, self.hour_edit).selectAll()
            elif self.focus == TimeWidget.FOCUS_HOUR:
                self.focus = TimeWidget.FOCUS_MINUTE
                _cast(EditWidget, self.minute_edit).selectAll()
            elif self.focus == TimeWidget.FOCUS_MINUTE:
                self.focus = TimeWidget.FOCUS_SECOND
                _cast(EditWidget, self.second_edit).selectAll()
            self.paint()

        else:
            if self.focus == TimeWidget.FOCUS_YEAR:
                _cast(EditWidget, self.year_edit).onKeyDown(vk, mod)
            elif self.focus == TimeWidget.FOCUS_MONTH:
                _cast(EditWidget, self.month_edit).onKeyDown(vk, mod)
            elif self.focus == TimeWidget.FOCUS_DAY:
                _cast(EditWidget, self.day_edit).onKeyDown(vk, mod)
            elif self.focus == TimeWidget.FOCUS_HOUR:
                _cast(EditWidget, self.hour_edit).onKeyDown(vk, mod)
            elif self.focus == TimeWidget.FOCUS_MINUTE:
                _cast(EditWidget, self.minute_edit).onKeyDown(vk, mod)
            elif self.focus == TimeWidget.FOCUS_SECOND:
                _cast(EditWidget, self.second_edit).onKeyDown(vk, mod)

    ## \~japanese
    # 親から文字コードchとMODKEY_*のmodを配送します。戻り値は編集成否の判定に使いません。
    # \~english
    # Route a character code ch and MODKEY_* mod from the parent; do not use the return value to determine edit success.
    # \~
    def onChar(self, ch, mod):

        if "0123456789\b".find(chr(ch)) >= 0:
            if self.focus == TimeWidget.FOCUS_YEAR:
                _cast(EditWidget, self.year_edit).onChar(ch, mod)
            elif self.focus == TimeWidget.FOCUS_MONTH:
                _cast(EditWidget, self.month_edit).onChar(ch, mod)
            elif self.focus == TimeWidget.FOCUS_DAY:
                _cast(EditWidget, self.day_edit).onChar(ch, mod)
            elif self.focus == TimeWidget.FOCUS_HOUR:
                _cast(EditWidget, self.hour_edit).onChar(ch, mod)
            elif self.focus == TimeWidget.FOCUS_MINUTE:
                _cast(EditWidget, self.minute_edit).onChar(ch, mod)
            elif self.focus == TimeWidget.FOCUS_SECOND:
                _cast(EditWidget, self.second_edit).onChar(ch, mod)

    ## \~japanese
    # 現在状態を親へ描画します。戻り値None。親の描画・フォーカス更新から呼びます。
    # \~english
    # Paint current state into the parent; return None. Call from host painting/focus updates.
    # \~
    def paint(self):
        if not self.visible:
            return

        attribute_edit = ckitcore.Attribute(fg=ckit_theme.getColor("fg"))

        self.window.putString(
            self.x, self.y, self.width, 1, attribute_edit, "     /  /      :  :   "
        )

        _cast(EditWidget, self.year_edit).enableCursor(
            self.enable_cursor and self.focus == TimeWidget.FOCUS_YEAR
        )
        _cast(EditWidget, self.year_edit).paint()

        _cast(EditWidget, self.month_edit).enableCursor(
            self.enable_cursor and self.focus == TimeWidget.FOCUS_MONTH
        )
        _cast(EditWidget, self.month_edit).paint()

        _cast(EditWidget, self.day_edit).enableCursor(
            self.enable_cursor and self.focus == TimeWidget.FOCUS_DAY
        )
        _cast(EditWidget, self.day_edit).paint()

        _cast(EditWidget, self.hour_edit).enableCursor(
            self.enable_cursor and self.focus == TimeWidget.FOCUS_HOUR
        )
        _cast(EditWidget, self.hour_edit).paint()

        _cast(EditWidget, self.minute_edit).enableCursor(
            self.enable_cursor and self.focus == TimeWidget.FOCUS_MINUTE
        )
        _cast(EditWidget, self.minute_edit).paint()

        _cast(EditWidget, self.second_edit).enableCursor(
            self.enable_cursor and self.focus == TimeWidget.FOCUS_SECOND
        )
        _cast(EditWidget, self.second_edit).paint()

    ## \~japanese
    # 各入力欄を検証し、有効な(年, 月, 日, 時, 分, 秒)を返します。不正値はValueErrorで、入力値を保持します。
    # \~english
    # Validate and return (year, month, day, hour, minute, second). Raise ValueError for invalid values and retain the edited text.
    # \~
    def getValue(self):
        value = (
            int(_cast(EditWidget, self.year_edit).getText()),
            int(_cast(EditWidget, self.month_edit).getText()),
            int(_cast(EditWidget, self.day_edit).getText()),
            int(_cast(EditWidget, self.hour_edit).getText()),
            int(_cast(EditWidget, self.minute_edit).getText()),
            int(_cast(EditWidget, self.second_edit).getText()),
        )
        _datetime.datetime(*value)
        return value


# ----------------------------------------------------------------------------------------------------------------------------
#
# ----------------------------------------------------------------------------------------------------------------------------


## \~japanese
# プログレスバーウィジェット
# 
#
# setValueへ0〜1の数値または行別の数値リスト/タプルを渡すと確定進捗、Noneなら50msタイマーによる不定進捗です。
# リスト/タプルはコピーして0〜1へ補正し、入力を変更・保持しません。getValueは従来どおり内部リストを返します。
# getValueは最後の確定値を返し、busy中でもNoneにはなりません。busy_modeで区別します。
# タイマーは可視busy中だけ1件登録し、確定値・非表示・destroyで解除します。再表示時はbusyを再開します。親の前にdestroyを呼びます。
#
# \~english
# Progress-bar widget
# 
#
# setValue takes a number in 0..1 or a list/tuple of per-row values; None enables a 50 ms indeterminate animation.
# Lists/tuples are copied and clamped to 0..1 without modifying or retaining the input. getValue still exposes the internal list.
# getValue returns the last determinate value, including during busy mode; inspect busy_mode separately.
# One timer runs only while visible and busy; determinate mode, hiding or destroy removes it. Showing resumes busy mode. Destroy before the parent on the UI thread.
#
# \~
class ProgressBarWidget(Widget):
    busy_anim_speed = 0.4

    ## \~japanese
    # ProgressBarWidgetを構築します。引数・所有資源はクラス説明を参照してください。
    # \~english
    # Construct ProgressBarWidget; see the class description for arguments and owned resources.
    # \~
    def __init__(self, window, x, y, width, height):
        Widget.__init__(self, window, x, y, width, height)

        self._destroyed = False
        self._timer_active = False
        self.busy_mode = False
        self.busy_anim_phase = 0
        self.busy_anim_theta = 0
        self.busy_anim_chase = 0
        self.busy_anim_value = [0, 0]
        self.value = 0

        self.paint()

    ## \~japanese
    # 自身のタイマーを解除します。繰返し呼出し可能で、以後show/setValueは何もしません。親は破棄しません。戻り値None。
    # \~english
    # Remove this control's timer without destroying the parent. Repeated calls are safe; later show/setValue do nothing. Return None.
    # \~
    def destroy(self):
        self._destroyed = True
        self._updateTimer()

    ## \~japanese
    # 可視フラグを設定してpaintします。非表示でbusyタイマーを止め、再表示で再開します。既存描画は親から消去します。
    # \~english
    # Set visibility and paint. Hiding stops the busy timer; showing resumes it. Erase prior drawing from the parent.
    # \~
    def show(self, visible):
        if self._destroyed:
            return
        Widget.show(self, visible)
        self._updateTimer()
        self.paint()

    ## \~japanese
    # 現在状態を親へ描画します。戻り値None。親の描画・フォーカス更新から呼びます。
    # \~english
    # Paint current state into the parent; return None. Call from host painting/focus updates.
    # \~
    def paint(self):
        if not self.visible:
            return

        track_attr = ckitcore.Attribute(bg=ckit_theme.getColor("bg"))
        bar_attr = ckitcore.Attribute(bg=ckit_theme.getColor("select_bg"))
        values = self.value if isinstance(self.value, list) else [self.value]
        for row in range(self.height):
            self.window.putString(
                self.x, self.y + row, self.width, 1, track_attr, " " * self.width
            )
            if self.busy_mode:
                left = int(self.width * self.busy_anim_value[0])
                right = int(self.width * self.busy_anim_value[1])
            else:
                left = 0
                right = (
                    int(
                        self.width
                        * values[min(row * len(values) // self.height, len(values) - 1)]
                    )
                    if values
                    else 0
                )
            self.window.putString(
                self.x + left,
                self.y + row,
                right - left,
                1,
                bar_attr,
                " " * (right - left),
            )

    ## \~japanese
    # 確定進捗またはNone（不定進捗）を設定します。リスト/タプルはコピーして補正します。busyから同値へ戻す場合も再描画します。戻り値None。
    # @sa ProgressBarWidget
    # \~english
    # Set determinate progress or None for busy mode. Copy and clamp lists/tuples; repaint even when returning from busy to the same value. Return None.
    # @sa ProgressBarWidget
    # \~
    def setValue(self, value):
        if self._destroyed:
            return
        if value is not None:
            if isinstance(value, (list, tuple)):
                value = [min(max(item, 0.0), 1.0) for item in value]
            else:
                value = min(max(value, 0.0), 1.0)
            changed = self.busy_mode or self.value != value
            self.busy_mode = False
            self._updateTimer()
            if changed:
                self.value = value
                self.paint()
        elif not self.busy_mode:
            self.busy_mode = True
            self.busy_anim_phase = 0
            self.busy_anim_theta = 0
            self.busy_anim_chase = 0
            self.busy_anim_value = [0, 0]
            self._updateTimer()
            self.paint()

    def _updateTimer(self):
        active = self.busy_mode and self.visible and not self._destroyed
        if active and not self._timer_active:
            self.window.setTimer(self._onTimer, 50)
            self._timer_active = True
        elif not active and self._timer_active:
            self.window.killTimer(self._onTimer)
            self._timer_active = False

    ## \~japanese
    # 最後の確定値（数値または内部リスト）を返します。リストをコピーしません。
    # \~english
    # Return the last determinate number or internal list without copying.
    # \~
    def getValue(self):
        return self.value

    def _onTimer(self):
        if not self._timer_active or self._destroyed:
            return

        if self.busy_anim_phase == 0:
            self.busy_anim_theta += ProgressBarWidget.busy_anim_speed
            if self.busy_anim_theta > math.pi * 0.5:
                self.busy_anim_phase = 1

        elif self.busy_anim_phase == 1:
            self.busy_anim_theta += ProgressBarWidget.busy_anim_speed
            self.busy_anim_chase += ProgressBarWidget.busy_anim_speed
            if self.busy_anim_theta > math.pi:
                self.busy_anim_theta = math.pi
                self.busy_anim_phase = 2

        elif self.busy_anim_phase == 2:
            self.busy_anim_chase += ProgressBarWidget.busy_anim_speed
            if self.busy_anim_chase > math.pi:
                self.busy_anim_chase = math.pi
                self.busy_anim_phase = 3

        elif self.busy_anim_phase == 3:
            self.busy_anim_theta -= ProgressBarWidget.busy_anim_speed
            if self.busy_anim_theta < math.pi * 0.5:
                self.busy_anim_phase = 4

        elif self.busy_anim_phase == 4:
            self.busy_anim_theta -= ProgressBarWidget.busy_anim_speed
            self.busy_anim_chase -= ProgressBarWidget.busy_anim_speed
            if self.busy_anim_theta < 0:
                self.busy_anim_theta = 0
                self.busy_anim_phase = 5

        elif self.busy_anim_phase == 5:
            self.busy_anim_chase -= ProgressBarWidget.busy_anim_speed
            if self.busy_anim_chase < 0:
                self.busy_anim_chase = 0
                self.busy_anim_phase = 0

        value1 = math.cos(self.busy_anim_theta) * 0.5 + 0.5
        value2 = math.cos(self.busy_anim_chase) * 0.5 + 0.5

        self.busy_anim_value = [min(value1, value2), max(value1, value2)]

        self.paint()


## @} widget
