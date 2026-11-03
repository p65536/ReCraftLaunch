from typing import Literal as _Literal
from typing import overload as _overload

import clnch_isearch
import clnch_misc
import clnch_statusbar
import clnch_strings as strings

import ckit
from ckit.ckit_const import (
    ORIGIN_X_CENTER,
    ORIGIN_Y_CENTER,
    VK_DOWN,
    VK_END,
    VK_ESCAPE,
    VK_HOME,
    VK_NEXT,
    VK_PRIOR,
    VK_RETURN,
    VK_UP,
)
from ckit.ckit_misc import _cleanup_on_exit

HORIZONTAL_PADDING = 4  # Pixels per side at 100% display scaling.


def _split_list_result(result: int | tuple[int, int]) -> tuple[int, int | None]:
    """Keep returned modifiers; a scalar result carries no modifier information."""
    if isinstance(result, tuple):
        return result
    return result, None

## @cond japanese
## @addtogroup listwindow リストウインドウ機能
## @endcond
## @cond english
## @addtogroup listwindow List Windows
## @endcond
## @addtogroup listwindow
## @{

# --------------------------------------------------------------------


## \~japanese
# リストウインドウ
# 
#  各種のリスト形式ウインドウを実現しているクラスです。
# 
#  設定ファイル custom.py の configure_ListWindow に渡される window 引数は、ListWindow クラスのオブジェクトです。
# 
# \~english
# List window
# 
#  Implements windows that display lists of items.
# 
#  The window argument passed to configure_ListWindow in custom.py is a ListWindow instance.
# 
# \~
class ListWindow(ckit.TextWindow):
    ## \~japanese
    #  一覧ウィンドウを直接作成する。通常は資源管理も行うpopMenuを使います。
    #  @param x 中心位置の画面X座標（ピクセル）。
    #  @param y 中心位置の画面Y座標（ピクセル）。
    #  @param min_width 最小幅（表示セル数）。
    #  @param min_height 最小高さ（文字行数）。
    #  @param max_width 最大幅の整数（表示セル数）。Noneは作業領域以外の追加上限なし。
    #  @param max_height 最大高さの整数（文字行数）。Noneは作業領域以外の追加上限なし。
    #  @param parent_window 親ウィンドウ。
    #  @param show 初期表示するか。
    #  @param title タイトル文字列。
    #  @param items 文字列、または先頭が表示名のタプル・リストの一覧。Noneは空一覧。
    #  @param initial_select 初期選択の0始まり位置。通常は有効範囲を渡します。
    #  @param onekey_search Trueなら空の表示名を除いて先頭文字検索、FalseならFでインクリメンタルサーチ。
    #  @param onekey_decide 先頭文字の一致が1件なら即決するか。
    #  @param return_modkey getResultを(位置, 修飾キー)形式にするか。
    #  @param keydown_hook (vk, mod)を受け、真で標準キー処理を省略する関数。Noneはフックなし。
    #  @param statusbar_handler (width, select)を受けて文字列を返す関数。幅はセル、選択は0始まり。Noneは非表示。
    #  @param dropfiles_handler (x, y, filenames)を受けるドロップ関数。座標はクライアントピクセル、filenamesはパス列。
    #  @param opaque_normal 通常行を不透明背景で描くか。既定False。
    #  ステータス関数は描画だけでなくサイズ計測中にも呼びます。空一覧や取消では無効な選択位置も考慮します。
    #  改行・折返しと画面の作業領域でサイズを調整します。自分でmessageLoop・getResult・destroyと親の状態復帰を管理します。
    #  @sa popMenu, getResult
    #
    # \~english
    #  Construct a list window directly; prefer popMenu, which also manages resources.
    #  @param x Screen X coordinate of the center in pixels.
    #  @param y Screen Y coordinate of the center in pixels.
    #  @param min_width Minimum width in display cells.
    #  @param min_height Minimum height in character rows.
    #  @param max_width Maximum width in display cells; None adds no limit beyond the work area.
    #  @param max_height Maximum height in character rows; None adds no limit beyond the work area.
    #  @param parent_window Parent window.
    #  @param show Show initially.
    #  @param title Title text.
    #  @param items List of strings, or tuples/lists with the label first; None means empty.
    #  @param initial_select Zero-based initial selection; normally pass a valid index.
    #  @param onekey_search True for first-character search, skipping empty labels; otherwise F starts incremental search.
    #  @param onekey_decide Accept immediately when first-character search has one match.
    #  @param return_modkey Make getResult return (index, modifiers).
    #  @param keydown_hook Callback (vk, mod); true skips standard key handling. None means no hook.
    #  @param statusbar_handler Callback (width, select) returning text; width in cells, index zero-based. None hides status.
    #  @param dropfiles_handler Drop callback (x, y, filenames); client-pixel coordinates and path sequence.
    #  @param opaque_normal Paint normal rows with an opaque background; default False.
    #  Status callbacks also run for size measurement, not just paint. Account for invalid selections with empty lists/cancellation.
    #  Newlines, wrapping and monitor work area affect layout. Manage messageLoop/getResult/destroy and parent restoration yourself.
    #  @sa popMenu, getResult
    #
    # \~
    def __init__(
        self,
        x,
        y,
        min_width,
        min_height,
        max_width,
        max_height,
        parent_window,
        show=True,
        title="",
        items=None,
        initial_select=0,
        onekey_search=True,
        onekey_decide=False,
        return_modkey=False,
        keydown_hook=None,
        statusbar_handler=None,
        dropfiles_handler=None,
        opaque_normal=False,
    ):
        if items is None:
            items = []
        self.active = False
        self.isearch = None
        self._opaque_normal = opaque_normal

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
            activate_handler=self.onActivate,
            close_handler=self.onClose,
            keydown_handler=self.onKeyDown,
            char_handler=self.onChar,
            dropfiles_handler=dropfiles_handler,
            dpi_handler=self.onDpi,
            move_handler=self.onMove,
        )

        with _cleanup_on_exit(self.destroy, error_only=True):
            self.items = items
            self.select = initial_select
            self.title = title
            self.statusbar_handler = statusbar_handler
            self._size_request = (min_width, min_height, max_width, max_height)
            self._layout(x, y)
            self.show(show)

            self.command = ckit.CommandMap(self)

            self.title = title
            self.items = items
            self.scroll_info = ckit.ScrollInfo()
            self.select = initial_select
            self.result_mod = 0
            self.onekey_search = onekey_search
            self.onekey_decide = onekey_decide
            self.return_modkey = return_modkey
            self.keydown_hook = keydown_hook
            self.statusbar_handler = statusbar_handler

            self.status_bar = None
            self.status_bar_layer = None

            if statusbar_handler:
                self.status_bar = clnch_statusbar.StatusBar()
                self.status_bar_layer = clnch_statusbar.SimpleStatusBarLayer()
                self.status_bar.registerLayer(self.status_bar_layer)

            self.scroll_info.makeVisible(self.select, self.itemsHeight())

            self.configure()

            self.paint()

    ## \~japanese
    # 設定を読み込む
    # 
    #  キーマップなどをリセットした上で、custom.py の configure_ListWindow() を呼び出します。
    # 
    #  configure_ListWindow(window)は各一覧の作成時にも実行されます。mainのconfigureと別のフックです。
    #  一覧のキー関数にはargs=[]・mod=0のCommandInfoを渡します。Enter時の修飾はreturn_modkeyで結果として取得します。
    #  例: window.keymap["C-N"] = window.command.CursorDown。
    #  このフックの例外はcallConfigFuncが通知します。
    #  @sa getResult, CommandMap
    #
    # \~english
    # Load configuration
    # 
    #  Reset the keymap and apply configure_ListWindow() from custom.py.
    # 
    #  configure_ListWindow(window) also runs when each list is created, separately from the main configure hook.
    #  List key handlers receive CommandInfo with args=[] and mod=0. Obtain Enter modifiers through return_modkey in the result.
    #  Example: window.keymap["C-N"] = window.command.CursorDown.
    #  callConfigFunc reports exceptions raised by this hook.
    #  @sa getResult, CommandMap
    #
    # \~
    def configure(self):
        self.keymap = ckit.Keymap()
        self.keymap["Up"] = self.command.CursorUp
        self.keymap["Down"] = self.command.CursorDown
        self.keymap["PageUp"] = self.command.CursorPageUp
        self.keymap["PageDown"] = self.command.CursorPageDown
        self.keymap["Home"] = self.command.CursorFirst
        self.keymap["End"] = self.command.CursorLast
        self.keymap["Return"] = self.command.Enter
        self.keymap["Escape"] = self.command.Cancel
        if not self.onekey_search:
            self.keymap["F"] = self.command.IncrementalSearch
        ckit.callConfigFunc("configure_ListWindow", self)

    ## \~japanese
    # リストの項目を１つ削除する
    # 
    #  @param self  -
    #  @param index 削除する項目のインデックス
    # 
    #  itemsは呼出し元が渡したリストを保持するため、この操作は元リストにも反映されます。
    #  選択位置とスクロールを補正し再描画します。無効なindexはIndexErrorです。
    #  @return None。
    #
    # \~english
    # Remove one item from the list
    # 
    #  @param self  -
    #  @param index Index of the item to remove
    # 
    #  items retains the caller's supplied list, so this operation also modifies that list.
    #  Adjust selection/scrolling and repaint. An invalid index raises IndexError.
    #  @return None.
    #
    # \~
    def remove(self, index):
        del self.items[index]
        del self.item_lines[index]

        if self.select > index:
            self.select -= 1

        if not len(self.items):
            self.select = -1
            self.quit()
            return

        if self.select < 0:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
            self.select = 0
        if self.select > len(self.items) - 1:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
            self.select = len(self.items) - 1

        self.paint()

    def onActivate(self, active):
        self.active = active
        self.paint()

    def onClose(self):
        self.cancel()

    def onKeyDown(self, vk, mod):
        if self.keydown_hook and self.keydown_hook(vk, mod):
            return True

        try:
            func = self.keymap.table[ckit.KeyEvent(vk, mod)]
        except KeyError:
            return

        self.result_mod = mod
        func(ckit.CommandInfo())

        return True

    def onChar(self, ch, mod):
        if self.onekey_search:
            if 0x20 <= ch < 0x100:
                if not len(self.items):
                    return

                found = []

                for i in range(self.select + 1, len(self.items)):
                    item = self.items[i]
                    if isinstance(item, list) or isinstance(item, tuple):  # noqa: SIM101  # Retain short-circuit evaluation; excluded from cleanup for performance.
                        item = item[0]

                    if item and item[0].upper() == chr(ch).upper():
                        found.append(i)
                        if len(found) >= 2:
                            break

                if len(found) < 2:
                    for i in range(self.select + 1):
                        item = self.items[i]
                        if isinstance(item, list) or isinstance(item, tuple):  # noqa: SIM101  # Retain short-circuit evaluation; excluded from cleanup for performance.
                            item = item[0]

                        if item and item[0].upper() == chr(ch).upper():
                            found.append(i)
                            if len(found) >= 2:
                                break

                if found:
                    if self.onekey_decide and len(found) == 1:
                        self.select = found[0]
                        self.result_mod = mod
                        self.quit()
                    else:
                        self.select = found[0]
                        self.scroll_info.makeVisible(self.select, self.itemsHeight())
                        self.paint()

        else:
            if self.isearch:
                if ch == ord("\b"):
                    isearch_newvalue = self.isearch.isearch_value[:-1]
                elif ch == ord(" "):
                    return
                else:
                    isearch_newvalue = self.isearch.isearch_value + chr(ch)

                accept = False

                item = self.items[self.select]
                if isinstance(item, list) or isinstance(item, tuple):  # noqa: SIM101  # Retain short-circuit evaluation; excluded from cleanup for performance.
                    item = item[0]

                if self.isearch.fnmatch(item, isearch_newvalue):
                    accept = True
                else:
                    if self.isearch.isearch_type == "inaccurate":
                        isearch_type_list = ["strict", "partial", "inaccurate"]
                    else:
                        isearch_type_list = ["strict", "partial"]

                    last_type_index = isearch_type_list.index(self.isearch.isearch_type)
                    for isearch_type_index in range(last_type_index + 1):
                        for i in range(len(self.items)):
                            item = self.items[i]
                            if isinstance(item, list) or isinstance(item, tuple):  # noqa: SIM101  # Retain short-circuit evaluation; excluded from cleanup for performance.
                                item = item[0]

                            if self.isearch.fnmatch(
                                item,
                                isearch_newvalue,
                                isearch_type_list[isearch_type_index],
                            ):
                                self.select = i
                                self.scroll_info.makeVisible(
                                    self.select, self.itemsHeight()
                                )
                                accept = True
                                break
                        if accept:
                            break

                if accept:
                    self.isearch.isearch_value = isearch_newvalue
                    self.paint()

    def _layout(self, x, y, scale=None):
        padding = round(
            HORIZONTAL_PADDING * (self.getDisplayScaling() if scale is None else scale)
        )
        self.setHorizontalPadding(padding)
        min_width, min_height, max_width, max_height = self._size_request
        limit_width, limit_height = ckit.getWindowSizeLimits(self)
        self._size_limits = (limit_width, limit_height)
        char_width = self.getCharSize()[0]
        padding_columns = (padding * 2 + char_width - 1) // char_width
        limit_width -= padding_columns
        max_width = limit_width if max_width is None else max_width - padding_columns
        max_height = limit_height if max_height is None else max_height
        labels = [
            item[0] if isinstance(item, (list, tuple)) else item for item in self.items
        ]
        statuses = (
            [self.statusbar_handler(limit_width, i) for i in range(len(labels))]
            if self.statusbar_handler
            else []
        )
        content_width = max(
            (
                self.getStringWidth(part)
                for value in [self.title, *labels]
                for part in value.splitlines()
            ),
            default=0,
        )
        status_width = max(
            (
                self.getStringWidth(part) + 2
                for value in statuses
                for part in value.splitlines()
            ),
            default=0,
        )
        width = max(
            2,
            min(
                limit_width,
                max_width,
                max(min_width - padding_columns, content_width, status_width),
            ),
        )
        self.item_lines = [
            ckit.splitLines(self, label, width) or [""] for label in labels
        ]
        self.item_height = max((len(parts) for parts in self.item_lines), default=1)
        self.status_rows = (
            max(
                1,
                max(
                    (
                        len(ckit.splitLines(self, status, width - 2))
                        for status in statuses
                    ),
                    default=0,
                ),
            )
            if self.statusbar_handler
            else 0
        )
        height = min(
            limit_height,
            max(max_height, self.item_height + self.status_rows),
            max(min_height, len(labels) * self.item_height + self.status_rows),
        )
        self.setPosSize(x, y, width, height, ORIGIN_X_CENTER | ORIGIN_Y_CENTER)

    def onDpi(self, scale):
        if not hasattr(self, "scroll_info"):
            return
        self.setFontFromFontObject(clnch_misc.getDialogFont(scale))
        rect = self.getWindowRect()
        self._layout((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2, scale)
        self.scroll_info.makeVisible(self.select, self.itemsHeight())
        ckit.fitWindowToWorkArea(self)
        self.paint()

    def onMove(self, x, y):
        if (
            hasattr(self, "scroll_info")
            and ckit.getWindowSizeLimits(self) != self._size_limits
        ):
            self.onDpi(self.getDisplayScaling())

    def itemsHeight(self):
        return max(1, (self.height() - self.status_rows) // self.item_height)

    def paint(self):
        width = self.width()
        attribute_normal = ckit.Attribute(fg=ckit.getColor("fg"))
        attribute_item = (
            ckit.Attribute(fg=ckit.getColor("fg"), bg=ckit.getColor("bg"))
            if self._opaque_normal else attribute_normal
        )
        attribute_selected = ckit.Attribute(
            fg=ckit.getColor("select_fg"), bg=ckit.getColor("select_bg")
        )
        for row in range(self.height()):
            self.putString(0, row, width, 1, attribute_normal, " " * width)
        for i in range(self.itemsHeight()):
            index = self.scroll_info.pos + i
            if index < len(self.items):
                attr = (
                    attribute_selected
                    if self.active and self.select == index
                    else attribute_item
                )
                for row, line in enumerate(self.item_lines[index]):
                    y = i * self.item_height + row
                    if y < self.height() - self.status_rows:
                        self.putString(0, y, width, 1, attr, line)
        if self.status_bar:
            if self.isearch:
                message = strings.LIST_SEARCH.format(query=self.isearch.isearch_value)
            else:
                statusbar_handler = self.statusbar_handler
                select = self.select
                if statusbar_handler is None:
                    raise TypeError("'NoneType' object is not callable")
                message = statusbar_handler(width, select)
            for row, line in enumerate(ckit.splitLines(self, message, width - 2)):
                if row >= self.status_rows:
                    break
                status_bar_layer = self.status_bar_layer
                if status_bar_layer is None:
                    raise AttributeError(
                        "'NoneType' object has no attribute 'setMessage'", name="setMessage", obj=None
                    )
                status_bar_layer.setMessage(line)
                self.status_bar.paint(
                    self, 0, self.height() - self.status_rows + row, width, 1
                )
        elif self.isearch:
            self.setTitle(strings.LIST_SEARCH.format(query=self.isearch.isearch_value))
        else:
            self.setTitle(self.title)

    ## \~japanese
    #  一覧の選択結果を取得する
    #  @return return_modkey=Falseなら0始まりの選択位置。Trueなら(位置, 修飾キービット)。
    #  cancel()・OSの閉じる操作で位置は-1になります。標準Escは検索中なら検索だけを終了し、
    #  それ以外はcancel()を呼びます。
    #  結果取得後もこのメソッド自体はウィンドウを破棄しません。
    #  @sa popMenu, cancel
    #
    # \~english
    #  Read the list selection
    #  @return Zero-based selected index when return_modkey=False; otherwise (index, modifier_bits).
    #  cancel() and closing through the OS set index to -1. Standard Esc ends an active search only;
    #  otherwise it calls cancel().
    #  This method does not destroy the window after reading the result.
    #  @sa popMenu, cancel
    #
    # \~
    def getResult(self):
        if self.return_modkey:
            return self.select, self.result_mod
        else:
            return self.select

    ## \~japanese
    # リストウインドウをキャンセルして閉じる
    # \~english
    # Cancel and close the list window
    # \~
    def cancel(self):
        self.select = -1
        self.quit()

    # --------------------------------------------------------------------------

    def executeCommand(self, name, info):
        try:
            command = getattr(self, "command_" + name)
        except AttributeError:
            return False

        command(info)
        return True

    def enumCommand(self):
        for attr in dir(self):
            if attr.startswith("command_"):
                yield attr[len("command_") :]

    # --------------------------------------------------------
    # The following methods can be bound to keys.
    # --------------------------------------------------------

    ## \~japanese
    # カーソルを1つ上に移動させる
    # \~english
    # Move the cursor up one item
    # \~
    def command_CursorUp(self, info):
        self.select -= 1
        if self.select < 0:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
            self.select = 0
        self.scroll_info.makeVisible(self.select, self.itemsHeight())
        self.paint()

    ## \~japanese
    # カーソルを1つ下に移動させる
    # \~english
    # Move the cursor down one item
    # \~
    def command_CursorDown(self, info):
        self.select += 1
        if self.select > len(self.items) - 1:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
            self.select = len(self.items) - 1
        self.scroll_info.makeVisible(self.select, self.itemsHeight())
        self.paint()

    ## \~japanese
    # 1ページ上方向にカーソルを移動させる
    # \~english
    # Move the cursor up one page
    # \~
    def command_CursorPageUp(self, info):
        if self.isearch:
            return
        if self.select > self.scroll_info.pos:
            self.select = self.scroll_info.pos
        else:
            self.select -= self.itemsHeight()
            if self.select < 0:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
                self.select = 0
            self.scroll_info.makeVisible(self.select, self.itemsHeight())
        self.paint()

    ## \~japanese
    # 1ページ下方向にカーソルを移動させる
    # \~english
    # Move the cursor down one page
    # \~
    def command_CursorPageDown(self, info):
        if self.isearch:
            return
        if self.select < self.scroll_info.pos + self.itemsHeight() - 1:
            self.select = self.scroll_info.pos + self.itemsHeight() - 1
        else:
            self.select += self.itemsHeight()
        if self.select > len(self.items) - 1:  # noqa: PLR1730  # Keep conditional updates; min/max calls were slower in the reviewed paths.
            self.select = len(self.items) - 1
        self.scroll_info.makeVisible(self.select, self.itemsHeight())
        self.paint()

    ## \~japanese
    # 先頭項目へ移動する
    # \~english
    # Move to the first item
    # \~
    def command_CursorFirst(self, info):
        if not self.items:
            return
        self.select = 0
        self.scroll_info.makeVisible(self.select, self.itemsHeight())
        self.paint()

    ## \~japanese
    # 末尾項目へ移動する
    # \~english
    # Move to the last item
    # \~
    def command_CursorLast(self, info):
        if not self.items:
            return
        self.select = len(self.items) - 1
        self.scroll_info.makeVisible(self.select, self.itemsHeight())
        self.paint()

    ## \~japanese
    # 決定する
    # \~english
    # Accept the selection
    # \~
    def command_Enter(self, info):
        self.quit()

    ## \~japanese
    # キャンセルする
    # \~english
    # Cancel
    # \~
    def command_Cancel(self, info):
        self.cancel()

    ## \~japanese
    # インクリメンタルサーチを行う
    # \~english
    # Start incremental search
    # \~
    def command_IncrementalSearch(self, info):
        def finish():
            self.isearch = None
            self.keydown_hook = self.keydown_hook_old
            self.scroll_info.makeVisible(self.select, self.itemsHeight())
            self.paint()

        def getString(i):
            item = self.items[i]
            if isinstance(item, list) or isinstance(item, tuple):  # noqa: SIM101  # Retain short-circuit evaluation; excluded from cleanup for performance.
                item = item[0]
            return item

        def cursorUp():
            self.select = search.cursorUp(
                getString,
                len(self.items),
                self.select,
                self.scroll_info.pos,
                self.itemsHeight(),
            )
            self.scroll_info.makeVisible(self.select, self.itemsHeight())
            self.paint()

        def cursorDown():
            self.select = search.cursorDown(
                getString,
                len(self.items),
                self.select,
                self.scroll_info.pos,
                self.itemsHeight(),
            )
            self.scroll_info.makeVisible(self.select, self.itemsHeight())
            self.paint()

        def cursorPageUp():
            self.select = search.cursorPageUp(
                getString,
                len(self.items),
                self.select,
                self.scroll_info.pos,
                self.itemsHeight(),
            )
            self.scroll_info.makeVisible(self.select, self.itemsHeight())
            self.paint()

        def cursorPageDown():
            self.select = search.cursorPageDown(
                getString,
                len(self.items),
                self.select,
                self.scroll_info.pos,
                self.itemsHeight(),
            )
            self.scroll_info.makeVisible(self.select, self.itemsHeight())
            self.paint()

        def onKeyDown(vk, mod):
            if vk == VK_RETURN or vk == VK_ESCAPE:
                finish()
            elif vk == VK_UP:
                cursorUp()
            elif vk == VK_DOWN:
                cursorDown()
            elif vk == VK_PRIOR:
                cursorPageUp()
            elif vk == VK_NEXT:
                cursorPageDown()
            elif vk in (VK_HOME, VK_END):
                indices = (
                    range(len(self.items))
                    if vk == VK_HOME
                    else range(len(self.items) - 1, -1, -1)
                )
                for i in indices:
                    if search.fnmatch(getString(i), search.isearch_value):
                        self.select = i
                        self.scroll_info.makeVisible(self.select, self.itemsHeight())
                        self.paint()
                        break

            return True

        self.removeKeyMessage()

        search = clnch_isearch.IncrementalSearch()
        self.isearch = search
        self.keydown_hook_old = self.keydown_hook
        self.keydown_hook = onKeyDown
        self.scroll_info.makeVisible(self.select, self.itemsHeight())
        self.paint()


# Doxygen documents the implementation; overloads are for static typing.
## @cond
@_overload
def popMenu(
    main_window, max_width=None, max_height=None, title="", items=None,
    initial_select=0, onekey_search=True, onekey_decide=False,
    return_modkey: _Literal[False] = False, keydown_hook=None,
    statusbar_handler=None, min_width=5,
) -> int: ...


@_overload
def popMenu(
    main_window, max_width=None, max_height=None, title="", items=None,
    initial_select=0, onekey_search=True, onekey_decide=False, *,
    return_modkey: _Literal[True], keydown_hook=None,
    statusbar_handler=None, min_width=5,
) -> tuple[int, int]: ...


@_overload
def popMenu(
    main_window, max_width, max_height, title, items,
    initial_select, onekey_search, onekey_decide,
    return_modkey: _Literal[True], keydown_hook=None,
    statusbar_handler=None, min_width=5,
) -> tuple[int, int]: ...


@_overload
def popMenu(
    main_window, max_width=None, max_height=None, title="", items=None,
    initial_select=0, onekey_search=True, onekey_decide=False,
    return_modkey: bool = False, keydown_hook=None,
    statusbar_handler=None, min_width=5,
) -> int | tuple[int, int]: ...
## @endcond

## \~japanese
# ポップアップメニューを表示する
# 
#  @param main_window       MainWindowオブジェクト
#  @param max_width         メニューウインドウの最大幅 (表示セル単位)
#  @param max_height        メニューウインドウの最大高さ (文字行単位)
#  @param title             メニューウインドウのタイトルバーに表示する文字列
#  @param items             メニューに表示するアイテムのリスト
#  @param initial_select    初期選択位置
#  @param onekey_search     文字入力で項目の先頭文字を検索するか
#  @param onekey_decide     先頭文字の検索で候補が1つだけだったとき即時決定するか
#  @param return_modkey     メニューが閉じたときに押されていたモディファイアキーを取得するか
#  @param keydown_hook      キー入力イベントのフック
#  @param statusbar_handler ステータスバーに表示する文字列を返すハンドラ
#  @param min_width         メニューウインドウの最小幅 (表示セル数)
# 
#  @return                  引数 return_modkey が False の場合は結果値 (選択されたアイテムのインデックスか、キャンセルされた場合は-1)、引数 return_modkey が True の場合は ( 結果値, モディファイアキーの状態 ) を返す。
# 
#  引数 items には、( 表示名, ... ) 形式のアイテムをリストに格納して渡します。[ ... ] の部分には、どのようなデータが入ってもかまいません。
# 
#  onekey_search に True を渡したときは、キー入力で項目の先頭文字を検索します。onekey_search に False を渡したときは、F キーでインクリメンタルサーチが開始します。
# 
#  statusbar_handler にハンドラを渡したときは、ステータスバーが表示されます。
# 
#  インクリメンタルサーチの検索パターンは、ステータスバーが有効な場合はステータスバーに表示され、ステータスバーが無効な場合はタイトルバーに表示されます。
# 
#  max_width・max_heightは正の整数またはNoneです。省略した軸は作業領域以外の追加上限を設けません。
#  呼出しはUIスレッドで行います。親の無効化・復帰と一時一覧の破棄を行い、例外は後始末後に伝播します。
#  keydown_hook(vk, mod)は真で通常処理を省略します。statusbar_handler(width, select)は文字列を返し、
#  描画とサイズ計測に使います。widthは表示セル数です。
#  例: index = popMenu(window, 40, 12, title="Choose", items=[("One", 1), ("Two", 2)])。
#  items[index]を読む前にindex<0を調べ、return_modkey=Trueなら先にタプルを分解します。
#  @sa ListWindow
#
# \~english
# Display a popup menu
# 
#  @param main_window       MainWindow instance
#  @param max_width         Maximum menu width in display cells
#  @param max_height        Maximum menu height in character rows
#  @param title             Text displayed in the menu title bar
#  @param items             List of menu items
#  @param initial_select    Initially selected index
#  @param onekey_search     Search by the first character when typing
#  @param onekey_decide     Accept immediately when a first-character search has one match
#  @param return_modkey     Return the modifier keys held when the menu closes
#  @param keydown_hook      Hook for key-down events
#  @param statusbar_handler Handler returning the status-bar text
#  @param min_width         Minimum menu width in display cells
# 
#  @return                  If return_modkey is False, the selected index or -1 for cancellation. Otherwise, (result, modifier_key_state).
# 
#  Pass items as a list of tuples in the form (display_name, ...). The remaining fields may contain any data.
# 
#  With onekey_search=True, typing searches by the first character. Otherwise, F starts incremental search.
# 
#  Providing statusbar_handler enables the status bar.
# 
#  The incremental-search pattern appears in the status bar when enabled, or in the title bar otherwise.
# 
#  max_width/max_height accept positive integers or None; an omitted axis has no additional limit beyond the work area.
#  Call on the UI thread. Disable/restore the parent and destroy the temporary list; propagate errors after cleanup.
#  keydown_hook(vk, mod) returns true to skip standard handling. statusbar_handler(width, select) returns text
#  for drawing and size measurement; width is in display cells.
#  Example: index = popMenu(window, 40, 12, title="Choose", items=[("One", 1), ("Two", 2)]).
#  Check index<0 before reading items[index]; unpack first if return_modkey=True.
#  @sa ListWindow
#
# \~
def popMenu(
    main_window,
    max_width=None,
    max_height=None,
    title="",
    items=None,
    initial_select=0,
    onekey_search=True,
    onekey_decide=False,
    return_modkey: bool = False,
    keydown_hook=None,
    statusbar_handler=None,
    min_width=5,
) -> int | tuple[int, int]:
    was_enabled = main_window.isEnabled()
    pos = main_window.centerOfWindowInPixel()
    list_window = ListWindow(
        pos[0],
        pos[1],
        min_width,
        1,
        max_width,
        max_height,
        main_window,
        False,
        title,
        items,
        initial_select=initial_select,
        onekey_search=onekey_search,
        onekey_decide=onekey_decide,
        return_modkey=return_modkey,
        keydown_hook=keydown_hook,
        statusbar_handler=statusbar_handler,
        opaque_normal=True,
    )
    with clnch_misc._modal_dialog_scope(main_window, list_window, was_enabled):
        clnch_misc.adjustWindowPosition(main_window, list_window, default_up=False)
        list_window.show(True)
        main_window.enable(False)
        list_window.messageLoop()
        result = list_window.getResult()
    return result


## @} listwindow
