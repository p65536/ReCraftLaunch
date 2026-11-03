# 日本語
# custom.pyはPythonで標準機能を拡張・上書きし、使う拡張を明示する設定ファイルです。
# 標準設定はConfig、アプリ・URL登録はcommands.jsonを使います。
#
# 使用例はすべて無効です。使う拡張のimportと関数呼び出しの行頭の「#」だけを削除してください。
# defとpassはそのまま残してください。「#」の後の空白4個は必要なインデントです。
#
# configureは起動・Reload時、configure_ListWindowは一覧の標準キー割当後に呼ばれます。
# 同じフックの定義は1つにまとめ、適用したい順に関数を呼びます。
#
# Reloadはcustom.pyと、明示importしたscripts/・extensions/のPythonソースを再評価します。
# 独自資源の終了処理はwindow.registerConfigCleanupへ登録します。詳細は拡張ガイドを参照してください。
# stamp: 現在日時をコピー。clock: 時計書式を変更。
# completion_keys: Alt+Spaceで補完を一時切替。list_keys: 一覧のCtrl+P／Ctrl+Nで上下移動。
# netdrive: NetDrive;L \\server\shareで割当、NetDrive;Lで解除。
# NetDrive実行時にネットワークドライブを変更します。同名のJSON登録を避けてください。
# my_commands: 選択中の設定保存先のscripts/my_commands.pyを自分で作成した場合の例です。


# English
# custom.py extends/overrides standard features and explicitly selects extensions.
# Use Config for standard settings and commands.json for app/URL registrations.
#
# Examples are disabled. Delete only the leading "#" from both the import and function call.
# Keep def and pass as written. The four spaces after "#" provide the required indentation.
#
# configure runs at startup/Reload; configure_ListWindow runs after standard list bindings.
# Define each hook once and call extension functions in the desired order.
#
# Reload reevaluates custom.py and Python sources explicitly imported from scripts/ and extensions/.
# Register owned-resource cleanup with window.registerConfigCleanup; see the extension guide.
# stamp: copy the date/time. clock: change the clock format.
# completion_keys: toggle completion with Alt+Space. list_keys: move up/down with Ctrl+P/Ctrl+N.
# netdrive: map with NetDrive;L \\server\share; unmap with NetDrive;L.
# Running NetDrive changes network drives. Avoid a JSON command with the same name.
# my_commands: an example for scripts/my_commands.py that you create in the selected settings location.


def configure(window):
    pass

#    import stamp
#    stamp.configure(window)

#    import netdrive
#    netdrive.configure(window)

#    import clock
#    clock.configure(window)

#    import completion_keys
#    completion_keys.configure(window)

#    import my_commands
#    my_commands.configure(window)


def configure_ListWindow(window):
    pass

#    import list_keys
#    list_keys.configure(window)
