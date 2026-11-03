# ドキュメント生成環境

リポジトリ内のPythonとDoxygenを使用します。システムへのツール導入やPATH変更は不要です。
以下のコマンドはリポジトリルートで実行します。
初回clone後は、先に[Python環境の構築](../developer/development.md#初回clone後の環境構築)を済ませてください。

## 導入

```powershell
.\Python315\tools\python.exe -B -m pip install -r tools/requirements-docs.txt
```

Docutils 0.23とPygments 2.21.0を、同梱Pythonの `Lib/site-packages/` に導入します。
`Python315/tools/Scripts/`の`rst2html.exe`・`pygmentize.exe`等も、このインストールによって生成されます。
Doxygen 1.18.0の導入先・取得元・SHA256・導入手順は
[third_party/doxygen/README.md](../third_party/doxygen/README.md) に記録しています。
ツール実体はGit管理外です。新しいcheckoutでは別途導入してください。
Python環境を更新・切り替えた場合も、上のpipコマンドでDocutils・Pygmentsを再導入し、`Python315/tools/python.exe -B -c "import docutils, pygments"`で確認します。旧`site-packages`や生成済み実行ファイルをコピーせず、既存のDoxygenは再導入せずに使います。安全な切り替え・復旧は[既存Python環境の更新](../developer/development.md#既存python環境の更新)を参照してください。

## 生成

```powershell
.\Python315\tools\python.exe -B makefile.py document
```

`docs/<lang>/index.txt`・`docs/<lang>/command_json.txt`・`docs/<lang>/differences.txt`・`docs/common/changes.txt` をHTMLに変換し、Doxygenが `clnch/` と
`ckit/` と、明示指定したckitcore・clnch_native・pyautoのネイティブソースおよびpyautoの入力部品・定数のAPI説明コメントを統合します。変換時にはUTF-8のBOMを読み飛ばします。
ヘッダーと基本CSSには導入版Doxygenの標準ファイルを使用し、既存のフッターを維持します。
RSTは `docs/obj/<lang>/*.htm_` の本文断片だけを生成し、CSSを本文へ埋め込みません。ページ見出しはDoxygenが出力し、RSTの文書タイトルはテンプレートで本文から除外して重複を避けます。index.txtの`{{APP_VERSION}}`は、clnch/clnch_resource.pyの正本から置換した`docs/obj/<lang>/index.txt`を経由します。DoxygenのPROJECT_NUMBERも同じ正本を使います。元原稿のプレビューではトークンをそのまま表示し、生成済みファイルのincludeには依存しません。
操作説明には現行の設定・操作を記述します。index.txtは初回利用と機能概要の把握を目的に、画面の項目・選択肢と具体例で使い方を説明します。INI記述例や保存値を追加せず、画像は説明に合わせて用意します。JSONのキー・構造・保存形式はcommand_json.txtの別ページで扱います。commands.mdは画面別のキー・マウス操作と組込コマンドの早見表で、DoxygenのMarkdown処理によりcommands.htmlへ変換します。先頭見出しはページタイトルとして扱い、本文内のリンクはGitHub形式の見出しIDで保持します。ReCraftLaunch・CraftLaunch・ckit・pyauto・Python・Expatのライセンス原文はlicenses.htmlへまとめます。ヘルプの復元手順はindex.txtのFAQで扱い、独立ページは設けません。ヘルプ内ではMarkdown・テキスト原稿へ直接リンクせず、生成HTMLへリンクします。配布ルートのCOMMANDS.ja.md・COMMANDS.en.mdとライセンス原文は引き続き同梱します。CraftLaunch 3.40を基に作成した由来、著作権、ライセンス、移植元の参照資料を保持し、機能差異は `docs/<lang>/differences.txt` で説明します。
`docs/common/changes.txt` はCraftLaunchの更新履歴として、ReCraftLaunchの操作説明と区別して日本語原文のみ掲載します。
ライセンスページの原稿は `docs/<lang>/licenses.md` です。見出しと説明文はこの原稿で管理します。生成処理は原稿と各コンポーネントのライセンス原文を `docs/obj/<lang>/` へコピーし、Doxygenの `\include{doc}` で条文を取り込みます。原本はルートの `LICENSE.md`、`licenses/craftlaunch_LICENSE.md`、`ckit/LICENSE.md`、`pyauto/LICENSE.md`、`licenses/python_LICENSE.txt`、`licenses/expat_LICENSE.txt` です。CraftLaunch原版は [crftwr/clnchのLICENSE.md](https://github.com/crftwr/clnch/blob/master/LICENSE.md) から取得し、条文を保持しています。PythonとExpatは生成用コピーだけを `\verbatim` で囲み、原文全体の書式・記号を保持します。配布ではルートの原本と `licenses/` をコピーし、ckit・pyautoの原本を `licenses/<component>_LICENSE.md` として追加します。生成用コピーや配布先の条文は独立管理しません。
操作一覧には初回設定・設定値・Python拡張の説明を重ねず、使い方と機能・設定の詳細はindex.txt、独自機能の実装手順はextensions.mdで扱います。環境変数や画面の引数欄で使う置換記号の例もRSTのマニュアル側で扱います。

API説明コメントはソース内で日英併記します。通常の説明は次の形式とし、識別子・引数名は翻訳しません。

APIの必要記述と実装例の検証基準は[Python拡張APIの記述と検証](../developer/api-documentation.md)を参照してください。利用者向けの完成例はdocs/ja・docs/enのextensions.mdに置き、Doxygenのextensions.htmlとして同梱します。

```python
## \~japanese
# 日本語の説明
# \~english
# English description
# \~
```

ページ・グループのタイトル（@mainpage／@page／@addtogroup）は、宣言ごとに@cond japanese／@cond englishと@endcondで囲みます。
生成時にOUTPUT_LANGUAGEとENABLED_SECTIONSを選択するため、本文・タイトル・Doxygenのナビゲーションが揃います。
グループの所属範囲を示す@{の直前には、条件外でタイトルなしの@addtogroupを置きます。無効な言語条件を挟むと、先行するグループ指定が所属範囲へ引き継がれないためです。
スクリーンショットなどの文書画像は言語別に docs/<lang>/images/ に配置します。

追加CSSは `tools/rst2html_pygments.css` を `HTML_EXTRA_STYLESHEET` で読み込みます。
適用範囲は `.rst-content` 内に限定し、配色にはDoxygenのテーマ変数を使います。
ライト／ダークはDoxygen標準のブラウザー設定への追従を使用します。
本文の標準サイズはDoxygenの `doxygen.css` にある14px、行間22pxです。変更する場合は `tools/rst2html_pygments.css` で上書きし、生成済みCSSを直接編集しません。

`docs/obj/` と `docs/html/` は言語別のGit管理外の出力です。`makefile.py document`は日英両方の出力を再生成します。<lang>はjaまたはenです。
生成後は `docs/html/<lang>/index.html` をブラウザーで開いてください。
必要なツールがない場合や外部コマンドが失敗した場合は、生成処理を停止します。

生成物のページ・画像・CSS・JavaScriptの参照先と画像コピーは、次のコマンドで確認できます。

```powershell
.\Python315\tools\python.exe -B tools/check_docs.py
.\Python315\tools\python.exe -B tools/check_docs.py --lang en
```

このチェックは同一ページ・別ページのHTMLアンカー、本文へのCSS埋込みの不在と共通CSSのコピーも検証します。licenses.htmlでは日英共通の6見出し・順序・アンカーと、各原本の全文（HTML表示による空白差のみ無視）を照合します。Pythonの長い原文も全体を対象とします。配布時のcheck_package_files.pyはルートLICENSE.mdとlicenses/の5ファイルの名前・大文字小文字・原本とのバイト一致を検査し、旧名や欠落も拒否します。
ブラウザーの表示・JavaScript動作は別途確認してください。
Doxygen 1.18.0のメンバー索引で発生する無効なアンカーは、
`DISABLE_INDEX = NO` と `HTML_DYNAMIC_MENUS = NO` の静的タブ構成で回避します。
`_` は対応する見出しへ移動し、2項目だけの変数ページには文字索引を生成しません。

このdocumentターゲットは文書だけを生成・検査します。本体の配布作成時にも自動で呼び出され、日英の生成HTMLをdocs/ja・docs/enへ同梱します。

## ヘルプ同梱の配布ZIP

```powershell
.\Python315\tools\python.exe -B makefile.py all
```

Releaseビルド・文書生成／参照検査・Python準備・配布作成後、本体とdocsを単一ZIPへ収録します。
生成物は日英同梱の単一`dist/ReCraftLaunch_<version>.zip`です。Configで言語を選び、再起動するとUIとF1ヘルプへ反映します。版はclnch/clnch_resource.pyの正本に従います。
本文とAPIリファレンスは日英を収録し、CraftLaunchの旧更新履歴は日本語のみです。個別のヘルプZIPは生成しません。
未作成の開発設定だけをサンプルから配置し、既存設定は保持します。dist/ReCraftLaunchは再作成します。常用環境は生成先と分けてください。

展開後も既存の検査を使用できます。

```powershell
.\Python315\tools\python.exe -B tools/check_docs.py <展開先>/ReCraftLaunch/docs/ja --lang ja
.\Python315\tools\python.exe -B tools/check_docs.py <展開先>/ReCraftLaunch/docs/en --lang en
```

[ヘルプ同梱ZIPの生成](../developer/development.md#ヘルプ同梱zipの生成)と
[配布資材の確認](../developer/release-verification.md#配布資材の確認)を参照してください。
