import clnch_misc
import clnch_strings as strings

import ckit
from ckit.ckit_const import (
    ORIGIN_X_CENTER,
    ORIGIN_X_LEFT,
    ORIGIN_Y_CENTER,
    ORIGIN_Y_TOP,
    VK_DOWN,
    VK_END,
    VK_ESCAPE,
    VK_HOME,
    VK_LEFT,
    VK_NEXT,
    VK_PRIOR,
    VK_RETURN,
    VK_RIGHT,
    VK_UP,
)
from ckit.ckit_misc import _cleanup_on_exit

## @cond japanese
## @addtogroup msgbox メッセージボックス機能
## @endcond
## @cond english
## @addtogroup msgbox Message Boxes
## @endcond
## @addtogroup msgbox
## @{

# --------------------------------------------------------------------

MSGBOX_TYPE_OK = 0
MSGBOX_TYPE_YESNO = 1

MSGBOX_RESULT_CANCEL = 0
MSGBOX_RESULT_OK = 1
MSGBOX_RESULT_YES = 2
MSGBOX_RESULT_NO = 3

# --------------------------------------------------------------------


## \~japanese
#  確認メッセージ用の一時TextWindowです。通常は親の状態と破棄を管理するpopMessageBoxを使います。
#  直接生成する場合はmessageLoop・getResult・destroyと親の無効化・復帰を呼出し元が所有します。
#  UIスレッドから操作し、結果値はMSGBOX_RESULT_*で比較します。
#  @sa popMessageBox
#
# \~english
#  Temporary TextWindow for confirmation messages. Prefer popMessageBox, which manages parent state and destruction.
#  Direct construction requires the caller to own messageLoop/getResult/destroy and parent disabling/restoration.
#  Operate on the UI thread and compare results against MSGBOX_RESULT_* constants.
#  @sa popMessageBox
#
# \~
class MessageBox(ckit.TextWindow):
    BUTTON_OK = 0
    BUTTON_YES = 1
    BUTTON_NO = 2

    ## \~japanese
    #  @param x 中心位置のスクリーンX座標（ピクセル）。
    #  @param y 中心位置のスクリーンY座標（ピクセル）。
    #  @param parent_window 親TextWindow。
    #  @param show 生成後に表示するか。
    #  @param msgbox_type MSGBOX_TYPE_OKまたはMSGBOX_TYPE_YESNO。
    #  @param title タイトル文字列。
    #  @param message メッセージ文字列。改行を使えます。
    #  @param return_modkey getResultを(結果, 修飾キー)形式にするか。
    #  親の状態管理・ループ・破棄は呼出し元が所有します。通常はpopMessageBoxを使ってください。
    #
    # \~english
    #  @param x Center X in screen pixels.
    #  @param y Center Y in screen pixels.
    #  @param parent_window Parent TextWindow.
    #  @param show Show after construction.
    #  @param msgbox_type MSGBOX_TYPE_OK or MSGBOX_TYPE_YESNO.
    #  @param title Title string.
    #  @param message Message string, optionally containing newlines.
    #  @param return_modkey Make getResult return (result, modifiers).
    #  The caller owns parent state, message loop and destruction; normally use popMessageBox.
    #
    # \~
    def __init__(
        self,
        x,
        y,
        parent_window,
        show=True,
        msgbox_type=MSGBOX_TYPE_OK,
        title="",
        message="",
        return_modkey=False,
    ):
        ckit.TextWindow.__init__(
            self,
            x=x,
            y=y,
            width=5,
            height=5,
            origin=ORIGIN_X_CENTER | ORIGIN_Y_CENTER,
            parent_window=parent_window,
            bg_color=ckit.getColor("bg"),
            cursor0_color=ckit.getColor("cursor0"),
            cursor1_color=ckit.getColor("cursor1"),
            show=False,
            resizable=False,
            title=title,
            minimizebox=False,
            maximizebox=False,
            close_handler=self.onClose,
            keydown_handler=self.onKeyDown,
            lbuttondown_handler=self.onLeftButtonDown,
            lbuttonup_handler=self.onLeftButtonUp,
            mousewheel_handler=self.onMouseWheel,
            dpi_handler=self.onDpi,
            move_handler=self.onMove,
        )

        with _cleanup_on_exit(self.destroy, error_only=True):
            self.msgbox_type = msgbox_type
            self.message = message
            self.title = title
            self.return_modkey = return_modkey
            self.scroll_pos = 0
            self.pressed_button = None
            self._layout(x, y)
            self.show(show)

            if self.msgbox_type == MSGBOX_TYPE_OK:
                self.focus = MessageBox.BUTTON_OK
            elif self.msgbox_type == MSGBOX_TYPE_YESNO:
                self.focus = MessageBox.BUTTON_YES
            else:
                assert False

            self.result = MSGBOX_RESULT_CANCEL
            self.result_mod = 0

            self.paint()

    def _layout(self, x, y):
        self.work_area = ckit.getWindowWorkArea(self)
        max_width, max_height = ckit.getWindowSizeLimits(self)
        self._size_limits = (max_width, max_height)
        labels = (
            [(MessageBox.BUTTON_OK, strings.BUTTON_OK)]
            if self.msgbox_type == MSGBOX_TYPE_OK
            else [
                (MessageBox.BUTTON_YES, strings.BUTTON_YES),
                (MessageBox.BUTTON_NO, strings.BUTTON_NO),
            ]
        )
        widths = [self.getStringWidth(label) + 2 for _, label in labels]
        total = sum(widths) + (len(labels) - 1) * 4
        body = ckit.splitLines(self, self.message, max(2, min(72, max_width - 2))) or [
            ""
        ]
        window_width = min(
            max_width,
            max(
                20,
                self.getStringWidth(self.title) + 4,
                max(map(self.getStringWidth, body)) + 2,
                total + 2,
            ),
        )
        self.message_lines = ckit.splitLines(
            self, self.message, min(72, window_width - 2)
        ) or [""]
        vertical = total > window_width - 2
        self.buttons, self.button_rows, self.button_lines = [], {}, {}
        button_heights = []
        for button, label in labels:
            parts = ckit.splitLines(self, label, window_width - 4) or [""]
            self.button_lines[button] = parts
            button_heights.append(len(parts))
        button_height = (
            sum(button_heights) + len(labels) - 1 if vertical else max(button_heights)
        )
        self.hint_rows = 1
        if len(self.message_lines) + button_height + 3 > max_height:
            hint = strings.MESSAGE_SCROLL.format(
                first=len(self.message_lines),
                last=len(self.message_lines),
                total=len(self.message_lines),
            )
            self.hint_rows = len(ckit.splitLines(self, hint, window_width - 2))
        footer = button_height + self.hint_rows + 2
        window_height = min(max_height, len(self.message_lines) + footer)
        self.visible_rows = max(1, window_height - footer)
        self.button_y = window_height - button_height - 1
        column = (window_width - total) // 2
        row = self.button_y
        for (button, label), width, height in zip(labels, widths, button_heights):
            if vertical:
                width = min(width, window_width - 2)
                column = (window_width - width) // 2
            self.buttons.append((button, label, column, width))
            self.button_rows[button] = row
            if vertical:
                row += height + 1
            else:
                column += width + 4
        self.scroll_pos = min(
            self.scroll_pos, max(0, len(self.message_lines) - self.visible_rows)
        )
        self.setPosSize(
            x, y, window_width, window_height, ORIGIN_X_CENTER | ORIGIN_Y_CENTER
        )

    def onDpi(self, scale):
        if not hasattr(self, "message"):
            return
        self.setFontFromFontObject(clnch_misc.getDialogFont(scale))
        rect = self.getWindowRect()
        self._layout((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
        ckit.fitWindowToWorkArea(self)
        self.paint()

    def onClose(self):
        self.quit()

    def onMove(self, x, y):
        if (
            hasattr(self, "buttons")
            and ckit.getWindowSizeLimits(self) != self._size_limits
        ):
            self.onDpi(self.getDisplayScaling())

    def onKeyDown(self, vk, mod):
        if vk == VK_HOME:
            self._scroll(-self.scroll_pos)
        elif vk == VK_END:
            self._scroll(len(self.message_lines))
        elif vk in (VK_UP, VK_DOWN, VK_PRIOR, VK_NEXT):
            delta = {
                VK_UP: -1,
                VK_DOWN: 1,
                VK_PRIOR: -self.visible_rows,
                VK_NEXT: self.visible_rows,
            }[vk]
            self._scroll(delta)
        elif vk == VK_LEFT:
            if self.focus == MessageBox.BUTTON_NO:
                self.focus = MessageBox.BUTTON_YES
                self.paint()
        elif vk == VK_RIGHT:
            if self.focus == MessageBox.BUTTON_YES:
                self.focus = MessageBox.BUTTON_NO
                self.paint()
        elif vk == VK_RETURN:
            if self.focus == MessageBox.BUTTON_OK:
                self.result = MSGBOX_RESULT_OK
                self.result_mod = mod
            elif self.focus == MessageBox.BUTTON_YES:
                self.result = MSGBOX_RESULT_YES
                self.result_mod = mod
            elif self.focus == MessageBox.BUTTON_NO:
                self.result = MSGBOX_RESULT_NO
                self.result_mod = mod
            self.quit()

        elif vk == VK_ESCAPE and (
            self.msgbox_type == MSGBOX_TYPE_OK or self.msgbox_type == MSGBOX_TYPE_YESNO
        ):
            self.result = MSGBOX_RESULT_CANCEL
            self.result_mod = mod
            self.quit()

    def _scroll(self, delta):
        self.scroll_pos = max(
            0, min(self.scroll_pos + delta, len(self.message_lines) - self.visible_rows)
        )
        self.paint()

    def onMouseWheel(self, x, y, wheel, mod):
        if wheel:
            lines = max(1, int(abs(wheel) * 3))
            self._scroll(-lines if wheel > 0 else lines)

    def _button_at(self, x, y):
        for button, _, column, width in self.buttons:
            row = self.button_rows[button]
            left, top = self.charToClient(column, row)
            right, bottom = self.charToClient(
                column + width, row + len(self.button_lines[button])
            )
            if left <= x < right and top <= y < bottom:
                return button
        return None

    def onLeftButtonDown(self, x, y, mod):
        self.pressed_button = self._button_at(x, y)
        if self.pressed_button is not None:
            self.focus = self.pressed_button
            self.setCapture()
            self.paint()

    def onLeftButtonUp(self, x, y, mod):
        pressed = self.pressed_button
        self.pressed_button = None
        if pressed is not None:
            self.releaseCapture()
            if self._button_at(x, y) == pressed:
                self.onKeyDown(VK_RETURN, mod)

    def paint(self):
        attribute_normal = ckit.Attribute(fg=ckit.getColor("fg"))
        attribute_normal_selected = ckit.Attribute(
            fg=ckit.getColor("select_fg"), bg=ckit.getColor("select_bg")
        )

        for row in range(self.height()):
            self.putString(
                0, row, self.width(), 1, attribute_normal, " " * self.width()
            )
        lines = self.message_lines[
            self.scroll_pos : self.scroll_pos + self.visible_rows
        ]
        for row, line in enumerate(lines, 1):
            message_width = self.getStringWidth(line)
            self.putString(
                (self.width() - message_width) // 2,
                row,
                message_width,
                1,
                attribute_normal,
                line,
            )
        if len(self.message_lines) > self.visible_rows:
            hint = strings.MESSAGE_SCROLL.format(
                first=self.scroll_pos + 1,
                last=self.scroll_pos + len(lines),
                total=len(self.message_lines),
            )
            for i, line in enumerate(ckit.splitLines(self, hint, self.width() - 2)):
                self.putString(
                    1,
                    self.visible_rows + 1 + i,
                    self.width() - 2,
                    1,
                    attribute_normal,
                    line,
                )
        for button, label, column, width in self.buttons:
            attr = (
                attribute_normal_selected if self.focus == button else attribute_normal
            )
            for i, line in enumerate(self.button_lines[button]):
                self.putString(
                    column + 1, self.button_rows[button] + i, width - 2, 1, attr, line
                )

    ## \~japanese
    #  @return return_modkey=FalseならMSGBOX_RESULT_*の整数。Trueなら(結果, 修飾キー)のタプル。
    #  閉じる・取消はMSGBOX_RESULT_CANCELです。この取得自体はウィンドウを破棄しません。
    #
    # \~english
    #  @return Integer MSGBOX_RESULT_* when return_modkey=False; otherwise (result, modifiers).
    #  Closing/canceling returns MSGBOX_RESULT_CANCEL. Reading does not destroy the window.
    #
    # \~
    def getResult(self):
        if self.return_modkey:
            return self.result, self.result_mod
        else:
            return self.result


## \~japanese
# メッセージボックスを表示する
# 
#  @param main_window    MainWindowオブジェクト
#  @param msgbox_type    メッセージボックスのタイプ
#  @param title          メッセージボックスのタイトルバーに表示する文字列
#  @param message        メッセージ文字列
#  @param return_modkey  閉じたときのモディファイアキーの状態を取得するかどうか
#  @return               引数 return_modkey が False の場合は結果値、引数 return_modkey が True の場合は ( 結果値, モディファイアキーの状態 ) を返す
# 
#  引数 msgbox_type には、以下のいずれかを渡します。
#    - clnch_msgbox.MSGBOX_TYPE_OK \n
#       [ OK ] ボタンを１つ備えたメッセージボックス
# 
#    - clnch_msgbox.MSGBOX_TYPE_YESNO \n
#       [はい] ボタンと [いいえ] ボタンを備えたメッセージボックス
# 
#  返値の結果値としては、以下のいずれかが返ります。
#    - clnch_msgbox.MSGBOX_RESULT_CANCEL \n
#       キャンセルされた
# 
#    - clnch_msgbox.MSGBOX_RESULT_OK \n
#       [ OK ]ボタンが選択された
# 
#    - clnch_msgbox.MSGBOX_RESULT_YES \n
#       [ はい ]ボタンが選択された
# 
#    - clnch_msgbox.MSGBOX_RESULT_NO \n
#       [ いいえ ]ボタンが選択された
# 
#  UIスレッドから呼びます。親を無効化し、戻る前に元の状態へ復帰して一時窓を破棄します。例外は後始末後に伝播します。
#  改行と折返し・スクロールで画面へ収めます。return_modkey=Trueでは取消もタプルなので、分解してから結果定数と比較します。
#  例: result = popMessageBox(window, MSGBOX_TYPE_YESNO, "Confirm", "Continue?")。
#  @sa MessageBox
#
# \~english
# Display a message box
# 
#  @param main_window    MainWindow instance
#  @param msgbox_type    Message-box type
#  @param title          Text displayed in the message-box title bar
#  @param message        Message text
#  @param return_modkey  Return the modifier keys held when the box closes
#  @return               The result if return_modkey is False; otherwise (result, modifier_key_state).
# 
#  Pass one of the following values as msgbox_type.
#    - clnch_msgbox.MSGBOX_TYPE_OK \n
#       A message box with one [OK] button
# 
#    - clnch_msgbox.MSGBOX_TYPE_YESNO \n
#       A message box with [Yes] and [No] buttons
# 
#  The result is one of the following values.
#    - clnch_msgbox.MSGBOX_RESULT_CANCEL \n
#       Canceled
# 
#    - clnch_msgbox.MSGBOX_RESULT_OK \n
#       [OK] selected
# 
#    - clnch_msgbox.MSGBOX_RESULT_YES \n
#       [Yes] selected
# 
#    - clnch_msgbox.MSGBOX_RESULT_NO \n
#       [No] selected
# 
#  Call on the UI thread. Disable the parent, restore its prior state and destroy the temporary window before returning.
#  Errors propagate after cleanup. Newlines, wrapping and scrolling fit content within the work area.
#  With return_modkey=True cancellation also returns a tuple: unpack before comparing result constants.
#  Example: result = popMessageBox(window, MSGBOX_TYPE_YESNO, "Confirm", "Continue?").
#  @sa MessageBox
#
# \~
def popMessageBox(main_window, msgbox_type, title, message, return_modkey=False):
    was_enabled = main_window.isEnabled()
    main_window_rect = main_window.getWindowRect()
    pos = (
        (main_window_rect[0] + main_window_rect[2]) // 2,
        (main_window_rect[1] + main_window_rect[3]) // 2,
    )
    msgbox = MessageBox(
        pos[0], pos[1], main_window, False, msgbox_type, title, message, return_modkey
    )
    with clnch_misc._modal_dialog_scope(main_window, msgbox, was_enabled):
        clnch_misc.adjustWindowPosition(main_window, msgbox, default_up=False)
        # Keep buttons within the work area even if the message fits neither above nor below the parent.
        rect = msgbox.getWindowRect()
        work = msgbox.work_area
        x = max(work[0], min(rect[0], work[2] - (rect[2] - rect[0])))
        y = max(work[1], min(rect[1], work[3] - (rect[3] - rect[1])))
        msgbox.setPosSize(
            x, y, msgbox.width(), msgbox.height(), ORIGIN_X_LEFT | ORIGIN_Y_TOP
        )
        msgbox.show(True)
        main_window.enable(False)
        msgbox.messageLoop()
        result = msgbox.getResult()
    return result


## @} msgbox
