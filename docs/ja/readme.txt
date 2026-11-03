ReCraftLaunch
Windows向けキーボードランチャー

ReCraftLaunchは、craftwareによるCraftLaunch 3.40を基にした派生版です。
p65536が独立して開発しており、craftwareはReCraftLaunchの開発には関与していません。
移植元との違いはdocs/ja/differences.htmlを参照してください。

動作環境
- Windows x64
- Python 3.15同梱（別途インストール不要）
- Microsoft Visual C++ v14 Redistributable（x64）
  必要に応じて最新版を導入してください。

インストール
1. https://github.com/p65536/ReCraftLaunch/releases から最新のReCraftLaunch_<version>.zipをダウンロードしてください。
2. 任意のフォルダにZIPを展開し、reclnch.exeを起動してください。
設定は既定でインストール先フォルダのsettings/に保存します。
configの「設定の保存先」で%APPDATA%\ReCraftLaunchを選ぶこともできますが、反映はアプリ再起動後で、既存設定の自動コピー・移動は行いません。

言語設定
日本語・英語のUIとヘルプを同梱しています。
初期言語は英語です。日本語に変更する手順は以下。
1. 設定メニューを開く（メイン入力欄にconfigと入力してEnter、またはメイン入力欄でCtrl+S押下）
2. 「Language」を開き「Japanese」を選択してEnter
3. ReCraftLaunchを再起動
   1. ReCraftLaunchを終了：メイン入力欄にquitと入力してEnter
   2. ReCraftLaunchを起動：reclnch.exeを実行

バージョンアップ
1. https://github.com/p65536/ReCraftLaunch/releases から最新のReCraftLaunch_<version>.zipをダウンロードしてください。
2. ZIP展開後のファイルをインストール先に上書きしてください。個人設定は上書きされません。

アンインストール
1. ReCraftLaunchを終了し、展開したフォルダを削除します。フォルダ内に保存した設定も削除されます。
2. 設定保存先にAppDataフォルダを利用している場合は%APPDATA%\ReCraftLaunchを削除します。
3. 自分で作成したショートカットやスタートアップ登録があれば削除します。
ReCraftLaunchはWindowsレジストリを変更しないため、レジストリの操作は不要です。

詳しい使い方
使い方や設定は、
docs/ja/index.htmlを参照してください。
起動後はF1でもヘルプを開けます。

ライセンス
LICENSE.mdおよびlicenses/を参照してください。
