from collections.abc import Callable as _Callable
from contextlib import ExitStack as _ExitStack

from ckit import ckit_misc, ckit_textwindow, ckit_theme, ckit_widget, ckitcore
from ckit.ckit_const import (
    MODKEY_SHIFT,
    ORIGIN_X_CENTER,
    ORIGIN_X_LEFT,
    ORIGIN_Y_CENTER,
    ORIGIN_Y_TOP,
    VK_DOWN,
    VK_ESCAPE,
    VK_NEXT,
    VK_PRIOR,
    VK_RETURN,
    VK_SPACE,
    VK_TAB,
    VK_UP,
)
from ckit.ckit_misc import _cleanup_on_exit

# --------------------------------------------------------------------

## @addtogroup widget
## @{

## \~japanese
#  複数の入力部品を持つTextWindow。ckit.Dialogとして取得し、UIスレッドから操作します。
#  生成時に表示し、最初の有効部品へフォーカスを設定しますが、親の無効化・復帰とmessageLoop・destroyは呼出し元が管理します。
#  EnterでRESULT_OK、Escまたは閉じるでRESULT_CANCELになります。Tab/Shift+Tabでフォーカスを巡回します。
#  項目のidは結果辞書のキーなので重複を避け、値が必要ないStaticTextにはidを付けません。
#  visible(dialog)が偽の項目は描画・入力・フォーカスから外れますが、getResultの辞書には保持する値が入ります。
#  部品のbuild・size・paint・onKeyDown・onCharはDialogから呼びます。通常は直接呼ばず、結果取得口を使います。
#  資源管理を含む完全な例は @ref extensions を参照してください。
#
# \~english
#  Multi-field TextWindow exposed as ckit.Dialog; operate on the UI thread.
#  Construction shows it and focuses the first available control, but the caller manages parent disabling/restoration,
#  messageLoop and destroy. Enter sets RESULT_OK; Esc/close sets RESULT_CANCEL. Tab/Shift+Tab cycle focus.
#  Item IDs are result-dictionary keys, so avoid duplicates. StaticText has no value ID.
#  Fields with false visible(dialog) are excluded from drawing/input/focus, but retained values still appear in getResult.
#  Dialog calls item build/size/paint/onKeyDown/onChar; normally use the result accessors instead of calling these directly.
#  See @ref extensions for a complete example including resource management.
#
# \~
class Dialog(ckit_textwindow.TextWindow):
    RESULT_CANCEL = 0
    RESULT_OK = 1

    ## \~japanese
    #  @param parent_window 既存の親TextWindow。
    #  @param text タイトル文字列。
    #  @param items Dialog.StaticText/Edit/CheckBox/Choice等の項目リスト。
    #  表示に失敗した場合は取得済み資源を解放して例外を伝播します。
    #
    # \~english
    #  @param parent_window Existing parent TextWindow.
    #  @param text Title text.
    #  @param items List of Dialog.StaticText/Edit/CheckBox/Choice items.
    #  On construction failure release acquired resources and propagate the error.
    #
    # \~
    def __init__(self, parent_window, text, items):
        self.parent_window = parent_window
        self.dialog_title = text
        self.scroll_pos = 0
        self.focus = None
        self.font_handler: _Callable[[float], ckitcore.Font] | None = None
        self.items = items

        parent_window_rect = parent_window.getWindowRect()
        window_x, window_y = (
            (parent_window_rect[0] + parent_window_rect[2]) // 2,
            (parent_window_rect[1] + parent_window_rect[3]) // 2,
        )

        ckit_textwindow.TextWindow.__init__(
            self,
            x=window_x,
            y=window_y,
            width=1,
            height=1,
            origin=ORIGIN_X_CENTER | ORIGIN_Y_CENTER,
            parent_window=parent_window,
            bg_color=ckit_theme.getColor("bg"),
            caret0_color=ckit_theme.getColor("caret0"),
            caret1_color=ckit_theme.getColor("caret1"),
            show=False,
            resizable=False,
            title=text,
            minimizebox=False,
            maximizebox=False,
            caret=True,
            close_handler=self.onClose,
            keydown_handler=self.onKeyDown,
            char_handler=self.onChar,
            mousewheel_handler=self.onMouseWheel,
            dpi_handler=self.onDpi,
            move_handler=self.onMove,
        )

        with _cleanup_on_exit(self.destroy, error_only=True):
            self.setCaretPosition(-1, -1)

            # Initialize controls.
            self.rebuildItems()

            # Adjust the window size.
            self.setPosSize(
                x=window_x,
                y=window_y,
                width=self.window_width,
                height=self.window_height,
                origin=ORIGIN_X_CENTER | ORIGIN_Y_CENTER,
            )
            self.show(True)

            # Set the initial focus.
            self.focus = 0
            while True:
                if self.focus >= len(self.items):
                    self.focus = None
                    break
                if self.items[self.focus].focusable():
                    break
                self.focus += 1

            self.result = Dialog.RESULT_CANCEL

            self.paint()

    ## \~japanese
    #  入力部品とウィンドウを破棄する。親の有効状態の復元は行いません。
    #  最初の解放失敗があっても残りの解放を試みます。破棄後はこのオブジェクト・内部部品を操作しません。
    #
    # \~english
    #  Destroy input controls and the window without restoring the parent's enabled state.
    #  Attempt remaining cleanup after an initial failure. Do not use this object or its controls after destruction.
    #
    # \~
    def destroy(self):
        with _ExitStack() as cleanup:
            cleanup.enter_context(_cleanup_on_exit(super().destroy))
            for item in reversed(self.items):
                if isinstance(item, Dialog.Edit) and item.widget is not None:
                    cleanup.enter_context(_cleanup_on_exit(item.widget.destroy))

    ## \~japanese
    #  RESULT_CANCELを設定してmessageLoopを終了する。破棄はしません。
    #
    # \~english
    #  Set RESULT_CANCEL and end messageLoop without destroying the window.
    #
    # \~
    def onClose(self):
        self.result = Dialog.RESULT_CANCEL
        self.quit()

    ## \~japanese
    #  RESULT_OKを設定してmessageLoopを終了する。値の適用・破棄は呼出し元が行います。
    #
    # \~english
    #  Set RESULT_OK and end messageLoop; the caller applies values and destroys the dialog.
    #
    # \~
    def onEnter(self):
        self.result = Dialog.RESULT_OK
        self.quit()

    ## \~japanese
    #  現在の表示条件に従って部品と配置を再構築する
    #  @return None。Edit等の内部部品を作成・破棄する場合があります。内部widget参照を保持しないでください。
    #  UIスレッドで呼び、必要ならpaintで再描画します。
    #
    # \~english
    #  Rebuild controls and layout using current visibility predicates
    #  @return None. May create/destroy internal edit controls; do not retain widget references.
    #  Call on the UI thread and repaint with paint when needed.
    #
    # \~
    def rebuildItems(self):
        self.max_width, self.max_height = ckit_misc.getWindowSizeLimits(self)
        x = 2
        y = 1
        self.window_width = max(4, self.getStringWidth(self.dialog_title) + 4)
        for item in self.items:
            item.build(self, x, y)
            w, h = item.size()
            self.window_width = max(self.window_width, w + 2 * 2)
            y += h
        self.content_height = y + 1
        self.window_height = min(self.max_height, self.content_height)
        self.window_width = min(self.max_width, self.window_width)
        self.scroll_pos = min(
            self.scroll_pos, max(0, self.content_height - self.window_height)
        )

        window_rect = self.getWindowRect()
        self.setPosSize(
            x=window_rect[0],
            y=window_rect[1],
            width=self.window_width,
            height=self.window_height,
            origin=ORIGIN_X_LEFT | ORIGIN_Y_TOP,
        )

    def onKeyDown(self, vk, mod):
        if self.focus is None:
            if vk == VK_ESCAPE:
                self.onClose()
            elif vk == VK_RETURN:
                self.onEnter()
            return
        item = self.items[self.focus]
        if vk == VK_TAB and mod in (0, MODKEY_SHIFT):
            direction = -1 if mod == MODKEY_SHIFT else 1
            for step in range(1, len(self.items) + 1):
                focus = (self.focus + direction * step) % len(self.items)
                if self.items[focus].focusable():
                    if isinstance(item, Dialog.Edit) and item.widget:
                        item.widget.closeList()
                    self.focus = focus
                    self.paint()
                    return
            return
        if item.onKeyDown(vk, mod):
            self.rebuildItems()
            self.paint()
            return

        if vk == VK_RETURN:
            self.onEnter()

        elif vk == VK_ESCAPE:
            self.onClose()

        elif vk == VK_UP:
            focus = self.focus
            while True:
                focus -= 1
                if focus < 0:
                    return
                if self.items[focus].focusable():
                    self.focus = focus
                    self.paint()
                    return

        elif vk == VK_DOWN:
            focus = self.focus
            while True:
                focus += 1
                if focus >= len(self.items):
                    return
                if self.items[focus].focusable():
                    self.focus = focus
                    self.paint()
                    return

        elif vk in (VK_PRIOR, VK_NEXT):
            delta = -self.height() if vk == VK_PRIOR else self.height()
            self.scroll_pos = max(
                0, min(self.scroll_pos + delta, self.content_height - self.height())
            )
            self.paint(ensure_visible=False)

    def onChar(self, ch, mod):
        if self.focus is None:
            return
        item = self.items[self.focus]
        item.onChar(ch, mod)

    ## \~japanese
    #  @param x 内容内のXセル位置。
    #  @param y スクロール前のYセル位置。
    #  @return スクロール位置を差し引き、文字面の余白を含めて変換したクライアント内のピクセル座標(x, y)。
    #
    # \~english
    #  @param x Content X cell.
    #  @param y Content Y cell before scrolling.
    #  @return Client-pixel (x, y) after subtracting the scroll position, including text-plane padding.
    #
    # \~
    def charToClient(self, x, y):
        return super().charToClient(x, y - self.scroll_pos)

    ## \~japanese
    #  @param x 内容内のXセル位置。
    #  @param y スクロール前のYセル位置。
    #  @return スクロール位置を反映した画面上のピクセル座標(x, y)。
    #
    # \~english
    #  @param x Content X cell.
    #  @param y Content Y cell before scrolling.
    #  @return Screen-pixel (x, y) adjusted for the scroll position.
    #
    # \~
    def charToScreen(self, x, y):
        return self.clientToScreen(*self.charToClient(x, y))

    def putString(self, x, y, width, height, attr, text, offset=0):
        return super().putString(
            x, y - self.scroll_pos, width, height, attr, text, offset
        )

    ## \~japanese
    #  @param x 内容内のXセル位置。
    #  @param y スクロール前のYセル位置。スクロール後に表示行の範囲外ならキャレットを非表示にします。
    #  @return None。(-1, -1)も非表示指定です。
    #
    # \~english
    #  @param x Content X cell.
    #  @param y Y cell before scrolling. Hide the caret when the scrolled row is outside the visible rows.
    #  @return None. (-1, -1) also hides the caret.
    #
    # \~
    def setCursorPos(self, x, y):
        if y >= 0:
            y -= self.scroll_pos
        if not 0 <= y < self.height():
            x, y = -1, -1
        return super().setCursorPos(x, y)

    def onMouseWheel(self, x, y, wheel, mod):
        self.scroll_pos = max(
            0,
            min(
                self.scroll_pos - round(wheel * 3),
                self.content_height - self.window_height,
            ),
        )
        self.paint(ensure_visible=False)

    def onDpi(self, scale):
        if not hasattr(self, "items"):
            return
        if self.font_handler:
            self.setFontFromFontObject(self.font_handler(scale))
        self.rebuildItems()
        ckit_misc.fitWindowToWorkArea(self)
        self.paint()

    def onMove(self, x, y):
        if hasattr(self, "items") and ckit_misc.getWindowSizeLimits(self) != (
            self.max_width,
            self.max_height,
        ):
            self.onDpi(self.getDisplayScaling())

    def paint(self, ensure_visible=True):
        if self.focus is not None and ensure_visible:
            item = self.items[self.focus]
            top = item.widget.y if hasattr(item, "widget") and item.widget else item.y
            self.scroll_pos = max(0, min(self.scroll_pos, top - 1))
            self.scroll_pos = max(self.scroll_pos, top + 2 - self.height())
        attr = ckitcore.Attribute(fg=ckit_theme.getColor("fg"))
        for row in range(self.height()):
            super().putString(0, row, self.width(), 1, attr, " " * self.width())
        for item in self.items:
            focused = self.focus is not None and (item == self.items[self.focus])
            item.paint(focused)

    ## \~japanese
    #  @param id 項目識別子。
    #  @return 対象項目の現在値。Editは文字列、Choiceは選択番号、CheckBoxは現在のチェック値。
    #  @exception KeyError 対応するidがない場合。重複idは最初の項目を返します。
    #
    # \~english
    #  @param id Item identifier.
    #  @return Current item value: string for Edit, selected index for Choice, current checked value for CheckBox.
    #  @exception KeyError No matching ID. Duplicate IDs return the first matching item.
    #
    # \~
    def getValueById(self, id):
        for item in self.items:
            if item.id == id:
                return item.getValue()
        raise KeyError(id)

    ## \~japanese
    #  @return (RESULT_OKまたはRESULT_CANCEL, 値の辞書)。None以外のidを持つ全項目を含み、非表示項目も除外しません。
    #  取消時の値を適用するかは呼出し元が判断します。ウィンドウの破棄前に取得してください。
    #
    # \~english
    #  @return (RESULT_OK or RESULT_CANCEL, values_dictionary). Include every non-None item ID, even hidden fields.
    #  The caller decides whether to apply canceled values. Read before destroying the window.
    #
    # \~
    def getResult(self):
        values = {}
        for item in self.items:
            if item.id is not None:
                values[item.id] = item.getValue()
        return (self.result, values)

    # --------------------------------------------------------------------

    ## \~japanese
    #  Dialogの部品用の基底クラス。visible=Noneは常時表示、関数指定時はvisible(dialog)の真偽を使います。
    #  組込部品を使う場合、Itemを直接生成する必要はありません。
    #
    # \~english
    #  Base class for dialog items. visible=None means always visible; a supplied visible(dialog) predicate decides visibility.
    #  No need to construct Item directly when using supplied controls.
    #
    # \~
    class Item:
        ## \~japanese
        #  @param visible Noneなら常時表示、指定時はvisible(dialog)の真偽を使う関数。
        #
        # \~english
        #  @param visible None for always visible, or a visible(dialog) predicate.
        #
        # \~
        def __init__(self, visible=None):
            self.dialog = None
            self.visible = visible

        def isVisible(self):
            return self.visible is None or self.visible(self.dialog)

    ## \~japanese
    #  値を持たない説明用テキスト。StaticText(indent, text, visible=None, align=ALIGN_LEFT)で作ります。
    #  indentは表示セル数、textは改行を含められる文字列です。alignはALIGN_LEFT/ALIGN_RIGHTです。
    #  長い行は利用可能幅で折り返し、フォーカス・結果辞書の対象にはしません。
    #
    # \~english
    #  Non-value explanatory text. Construct StaticText(indent, text, visible=None, align=ALIGN_LEFT).
    #  indent is in display cells; text may include newlines. align is ALIGN_LEFT/ALIGN_RIGHT.
    #  Wrap long lines to available width; exclude this item from focus and the result dictionary.
    #
    # \~
    class StaticText(Item):
        ## \~japanese
        #  @param indent 左余白の表示セル数。
        #  @param text 表示文字列。
        #  @param visible 表示条件。Noneまたはvisible(dialog)。
        #  @param align ALIGN_LEFTまたはALIGN_RIGHT。
        #
        # \~english
        #  @param indent Left indentation in display cells.
        #  @param text Display string.
        #  @param visible None or visible(dialog) predicate.
        #  @param align ALIGN_LEFT or ALIGN_RIGHT.
        #
        # \~
        def __init__(self, indent, text, visible=None, align=ckit_misc.ALIGN_LEFT):
            Dialog.Item.__init__(self, visible)
            self.id = None
            self.indent = indent
            self.text = text
            self.align = align

        def build(self, dialog, x, y):
            self.dialog = dialog
            self.x = x
            self.y = y
            available = getattr(dialog, "max_width", dialog.width()) - 4 - self.indent
            self.lines = ckit_misc.splitLines(dialog, self.text, max(2, available)) or [
                ""
            ]
            self.width = max(map(dialog.getStringWidth, self.lines))

        def size(self):
            if self.isVisible():
                return (self.width + self.indent, len(self.lines))
            else:
                return (0, 0)

        def focusable(self):
            return False

        def onKeyDown(self, vk, mod):
            pass

        def onChar(self, ch, mod):
            pass

        def paint(self, focused):
            if not self.isVisible():
                return
            attr = ckitcore.Attribute(fg=ckit_theme.getHintColor())
            for row, line in enumerate(self.lines):
                x = self.x + self.indent
                if self.align == ckit_misc.ALIGN_RIGHT:
                    x = self.dialog.width() - 2 - self.indent - self.dialog.getStringWidth(line)
                width = self.dialog.getStringWidth(line) if self.align == ckit_misc.ALIGN_RIGHT else self.width
                self.dialog.putString(x, self.y + row, width, 1, attr, line)

    # --------------------------------------------------------------------

    ## \~japanese
    #  1行入力項目。Edit(id, indent, width, text, value, ...)で作ります。
    #  idは結果のキー、indent・widthは表示セル、textはラベル、valueは初期文字列です。
    #  候補・更新・単語境界等の追加引数はEditWidgetへ転送します。visibleはvisible(dialog)形式です。
    #  初期選択は全文。getValueは現在の文字列を返し、非表示なら最後に保持した値です。
    #  @sa EditWidget
    #
    # \~english
    #  Single-line input. Construct Edit(id, indent, width, text, value, ...).
    #  id is the result key; indent/width use display cells; text is the label and value the initial string.
    #  Completion/update/word-break options are forwarded to EditWidget; visible takes visible(dialog).
    #  Initially select all text. getValue returns current text, or the retained value while hidden.
    #  @sa EditWidget
    #
    # \~
    class Edit(Item):
        ## \~japanese
        #  id・indent・width・text・valueはDialog.Editのクラス説明を参照してください。
        #  追加引数のauto_complete/autofix_list/update_handler/candidate_handler/candidate_remove_handler/word_break_handlerはEditWidgetと同じです。
        #  visibleはNoneまたはvisible(dialog)で、EditWidgetへは渡しません。
        #
        # \~english
        #  See the Dialog.Edit class description for id/indent/width/text/value.
        #  auto_complete/autofix_list/update_handler/candidate_handler/candidate_remove_handler/word_break_handler follow EditWidget.
        #  visible is None or visible(dialog), and is not passed to EditWidget.
        #
        # \~
        def __init__(
            self,
            id,
            indent,
            width,
            text,
            value,
            auto_complete=False,
            autofix_list=None,
            update_handler=None,
            candidate_handler=None,
            candidate_remove_handler=None,
            word_break_handler=None,
            visible=None,
        ):
            Dialog.Item.__init__(self, visible)
            self.id = id
            self.indent = indent
            self.width = width
            self.requested_width = width
            self.text = text
            self.value = value
            self.selection = [0, len(self.value)]
            self.auto_complete = auto_complete
            self.autofix_list = autofix_list
            self.update_handler = update_handler
            self.candidate_handler = candidate_handler
            self.candidate_remove_handler = candidate_remove_handler
            self.word_break_handler = word_break_handler
            self.widget = None

        def build(self, dialog, x, y):
            self.dialog = dialog
            self.x = x
            self.y = y

            if self.isVisible():
                self.width = min(
                    self.requested_width, self.dialog.max_width - 4 - self.indent
                )
                label_width = self.dialog.getStringWidth(self.text) + 2
                self.label_lines = []
                if label_width + 12 > self.width:
                    self.label_lines = ckit_misc.splitLines(
                        dialog, self.text, self.width
                    )
                    label_width = 0
                edit_y = y + len(self.label_lines)
                if not self.widget:
                    self.widget = ckit_widget.EditWidget(
                        self.dialog,
                        x + self.indent + label_width,
                        edit_y,
                        self.width - label_width,
                        1,
                        self.value,
                        [0, len(self.value)],
                        auto_complete=self.auto_complete,
                        autofix_list=self.autofix_list,
                        update_handler=self.update_handler,
                        candidate_handler=self.candidate_handler,
                        candidate_remove_handler=self.candidate_remove_handler,
                        word_break_handler=self.word_break_handler,
                    )
                else:
                    self.widget.setPosSize(
                        x + self.indent + label_width,
                        edit_y,
                        self.width - label_width,
                        1,
                    )
            else:
                if self.widget:
                    self.value = self.widget.getText()
                    self.widget.destroy()
                    self.widget = None

        def size(self):
            if self.widget:
                return (self.width + self.indent, 1 + len(self.label_lines))
            else:
                return (0, 0)

        def focusable(self):
            return self.isVisible()

        def getValue(self):
            if self.widget:
                return self.widget.getText()
            else:
                return self.value

        def onKeyDown(self, vk, mod):
            if not self.widget:
                return False

            # Do not complete with Space.
            if vk == VK_SPACE:
                return False

            if self.widget.isListOpened():
                # Close the completion list with Enter/Esc.
                if vk == VK_RETURN or vk == VK_ESCAPE:
                    self.widget.closeList()
                    return True
            else:
                # Do not open the completion list with Up/Down.
                if vk == VK_UP or vk == VK_DOWN:
                    return False

            return self.widget.onKeyDown(vk, mod)

        def onChar(self, ch, mod):
            if self.widget:
                self.widget.onChar(ch, mod)

        def paint(self, focused):
            if not self.widget:
                return

            if focused:
                attr = ckitcore.Attribute(
                    fg=ckit_theme.getColor("select_fg"),
                    bg=ckit_theme.getColor("select_bg"),
                )
            else:
                attr = ckitcore.Attribute(fg=ckit_theme.getColor("fg"))

            for row, line in enumerate(self.label_lines or [self.text]):
                self.dialog.putString(
                    self.x + self.indent, self.y + row, self.width, 1, attr, line
                )

            self.widget.enableCursor(focused)
            self.widget.paint()

    # --------------------------------------------------------------------

    ## \~japanese
    #  チェック項目。CheckBox(id, indent, text, value, visible=None)で作ります。
    #  idは結果のキー、indentは表示セル、textはラベル、valueは初期のチェック値（通常bool）です。
    #  Spaceで切替え、getValueは現在のチェック値を返します。
    #
    # \~english
    #  Checkbox field. Construct CheckBox(id, indent, text, value, visible=None).
    #  id is the result key; indent uses display cells, text is the label, and value the initial checked value (normally bool).
    #  Space toggles it; getValue returns the current checked value.
    #
    # \~
    class CheckBox(Item):
        ## \~japanese
        #  @param id 結果辞書のキー。
        #  @param indent 左余白セル数。
        #  @param text ラベル文字列。
        #  @param value 初期チェック値。
        #  @param visible Noneまたはvisible(dialog)。
        #
        # \~english
        #  @param id Result dictionary key.
        #  @param indent Left indentation in cells.
        #  @param text Label string.
        #  @param value Initial checked value.
        #  @param visible None or visible(dialog).
        #
        # \~
        def __init__(self, id, indent, text, value, visible=None):
            Dialog.Item.__init__(self, visible)
            self.id = id
            self.indent = indent
            self.text = text
            self.value = value
            self.widget = None

        def build(self, dialog, x, y):
            self.dialog = dialog
            self.x = x
            self.y = y

            if self.isVisible():
                self.width = self.dialog.getStringWidth(self.text) + 3
                if not self.widget:
                    self.widget = ckit_widget.CheckBoxWidget(
                        self.dialog,
                        x + self.indent,
                        y,
                        self.width,
                        1,
                        self.text,
                        self.value,
                    )
                else:
                    self.widget.setPosSize(x + self.indent, y, self.width, 1)
            else:
                if self.widget:
                    self.value = self.widget.getValue()
                    self.widget = None

        def size(self):
            if self.widget:
                return (self.width + self.indent, 1)
            else:
                return (0, 0)

        def focusable(self):
            return self.isVisible()

        def getValue(self):
            if self.widget:
                return self.widget.getValue()
            else:
                return self.value

        def onKeyDown(self, vk, mod):
            if self.widget:
                return self.widget.onKeyDown(vk, mod)

        def onChar(self, ch, mod):
            pass

        def paint(self, focused):
            if not self.widget:
                return
            self.widget.enableCursor(focused)
            self.widget.paint()

    # --------------------------------------------------------------------

    ## \~japanese
    #  択一項目。Choice(id, indent, text, items, value, visible=None)で作ります。
    #  itemsは表示文字列のリスト、valueは有効範囲の0始まり初期番号です。左右キーで移動します。
    #  idは結果のキー、indentは表示セル、textはラベルです。getValueは表示文字列でなく選択番号を返します。
    #
    # \~english
    #  Single-choice field. Construct Choice(id, indent, text, items, value, visible=None).
    #  items is a list of labels; value is a valid zero-based initial index. Left/Right change the choice.
    #  id is the result key; indent uses display cells and text is the label. getValue returns the index, not the label.
    #
    # \~
    class Choice(Item):
        ## \~japanese
        #  @param id 結果辞書のキー。
        #  @param indent 左余白セル数。
        #  @param text ラベル文字列。
        #  @param items 空でない選択肢文字列リスト。
        #  @param value 有効範囲の0始まり初期選択番号。
        #  @param visible Noneまたはvisible(dialog)。
        #
        # \~english
        #  @param id Result dictionary key.
        #  @param indent Left indentation in cells.
        #  @param text Label string.
        #  @param items Nonempty list of choice strings.
        #  @param value Valid zero-based initial index.
        #  @param visible None or visible(dialog).
        #
        # \~
        def __init__(self, id, indent, text, items, value, visible=None):
            Dialog.Item.__init__(self, visible)
            self.id = id
            self.indent = indent
            self.text = text
            self.items = items
            self.value = value
            self.widget = None

        def build(self, dialog, x, y):
            self.dialog = dialog
            self.x = x
            self.y = y

            if self.isVisible():
                self.width = self.dialog.getStringWidth(self.text)
                for item in self.items:
                    self.width += self.dialog.getStringWidth(item) + 2
                self.width = min(
                    self.width + 2, self.dialog.max_width - 4 - self.indent
                )
                if not self.widget:
                    self.widget = ckit_widget.ChoiceWidget(
                        self.dialog,
                        x + self.indent,
                        y,
                        self.width,
                        1,
                        self.text,
                        self.items,
                        self.value,
                    )
                else:
                    self.widget.setPosSize(
                        x + self.indent, y, self.width, 1
                    )
            else:
                if self.widget:
                    self.value = self.widget.getValue()
                    self.widget = None

        def size(self):
            if self.widget:
                return (self.width + self.indent, self.widget.height)
            else:
                return (0, 0)

        def focusable(self):
            return self.isVisible()

        def getValue(self):
            if self.widget:
                return self.widget.getValue()
            else:
                return self.value

        def onKeyDown(self, vk, mod):
            if self.widget:
                return self.widget.onKeyDown(vk, mod)

        def onChar(self, ch, mod):
            pass

        def paint(self, focused):
            if not self.widget:
                return
            self.widget.enableCursor(focused)
            self.widget.paint()


## @} widget
