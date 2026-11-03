# 変更内容別のビルド・パッケージ手順

日常の開発確認では変更に必要な工程だけを実行し、配布物を更新するときは配布フォルダとZIPまで更新します。本書は工程の選び方を扱います。環境構築と各工程の詳細は[開発環境](development.md)、テストの選択は[配布版の確認手順](release-verification.md)を参照してください。

配布制御はmakefile.pyに一元化しています。配布更新は常に全生成し、ネイティブ再利用・収集専用・工程省略のモードは設けません。

## 作業開始時の判断

1. 確認先を決める。Debug開発実行、Release開発実行、生成ヘルプ、配布フォルダ、ZIPは別の成果物です。
2. 下表から必要な工程を選ぶ。複数種類の変更では必要工程を合わせ、同じ生成は1回だけ実行します。
3. 対象構成のEXE・PYD・runtimeが未作成、依存物を更新済み、または生成元が不明なら、先に環境を準備します。変更がない既存成果物を再利用する手順は、生成元と条件を確認できる場合に限ります。
4. 関連するテストと生成時の組込み検査を行う。生成コマンドは機能テスト全体の代わりにはなりません。
5. 配布対象を変更した作業の完了時には、現行では`makefile.py release`で配布フォルダとZIPを更新します。GitHub上の説明・開発文書・テストだけの変更では不要です。

生成・ビルド・パッケージ作業は順次実行します。とくに`compile`と配布処理は同じRelease用library.zipを更新します。

## 変更内容と必要工程

「配布更新」は、現行では下記の[一括生成](#配布フォルダとzipの一括生成)を使うことを意味します。必要最小限の生成と、現行ツールが一括実行する範囲を区別しています。

| 変更対象 | 開発確認に必要な工程 | 配布物への反映・理由 |
|---|---|---|
| ルート`README.md`・`README.ja.md` | ビルド不要。相対リンク・画像・テキスト形式を確認 | GitHubで表示する原稿で、配布物・ヘルプの入力ではない。配布更新不要。導入要件等を変えた場合は配布用readmeの記載も照合する |
| README専用`assets/recraftlaunch_actions_diagram.*.svg` | ビルド不要。対応READMEで表示確認 | 配布対象外。配布更新不要。EXEに埋め込むアイコンとは区別する |
| `developer/*.md`などHTML生成対象外の開発文書 | ビルド不要。リンク・テキスト形式を確認 | 配布更新不要。本書の変更もこの分類 |
| `clnch/*.py`の処理 | Debugはソースを使うため再起動。Releaseは`compile`後に再起動。C++ビルド不要 | library.zipを更新して配布更新。公開APIの説明・宣言・索引に影響する変更なら`document`も必要 |
| `clnch/clnch_strings_ja.py`・`clnch_strings_en.py`等のUI文言 | 上と同じ。文言・プレースホルダー・配置の関連テスト | 配布更新。ヘルプの説明や画面例も変わる場合は原稿も修正。文言だけならC++ビルドは不要 |
| `ckit/*.py`・`pyauto/*.py`の配布対象モジュール | Debugは再起動、Releaseは`compile`。同じディレクトリのC++は別扱い | 配布更新。Doxygenの入力に含まれるAPI説明・宣言の変更は`document`も実行 |
| Python内のAPI説明コメントだけ | `document`で生成ヘルプを確認。動作確認のためのC++ビルド不要 | Pythonソースはpycの生成元でもあるため、配布更新時は`compile`も含める。通常コメントだけでヘルプ入力に影響しない場合は`document`不要 |
| `clnch/main.cpp`、`clnch_native/`、`ckit/ckitcore/`、`pyauto/pyautocore/`のC/C++・ヘッダー | 使用構成の該当プロジェクトをNative Build。初回runtime準備は`copy`。Pythonも変更していなければ`compile`不要 | 配布更新。API説明・公開宣言に影響すれば`document`も必要。配布工程は4プロジェクトのRelease Rebuildを行う |
| ネイティブソース内のAPI説明コメントだけ | ヘルプ確認には`document`だけでよい | バイナリの動作変更はないが、現行の配布更新はRelease Rebuildを含む。Doxygen専用の説明を変えてもPythonの`compile`自体は不要 |
| `.vcxproj`・`.sln`・コンパイラ／SDK設定 | 該当構成のNative Build。出力先・ABI・CRT設定を変えた場合はRebuildと構成分離検査 | 配布工程に関係する場合は配布更新。ビルド設定だけではPythonやヘルプを更新しない |
| `clnch/clnch.rc`・`clnch/resource.h`・`assets/app.ico` | ReCraftLaunchプロジェクトのNative Build | EXEの資材なので配布更新。ヘルプ用`docs/<lang>/images/app_icon.png`は独立した原稿で、必要なら別途更新 |
| `clnch/clnch_resource.py`の`clnch_version` | Native Build、`compile`、`document`のすべて。EXE・library.zip・ヘルプへ番号を反映 | 配布更新。正本・EXE・library.zipの版が不一致ならパッケージ検査が拒否する |
| `docs/ja/`・`docs/en/`の`index.txt`・`differences.txt`・`command_json.txt`・`extensions.md`・`licenses.md`、`docs/common/changes.txt` | `document`。C++ビルド・`compile`不要 | 生成HTMLが変わるため配布更新。日本語だけの原稿変更でも現行`document`は日英両方を生成・検査する |
| `docs/<lang>/commands.md` | `document`。HTMLと原稿を確認 | ヘルプのcommands.htmlと配布ルートのCOMMANDS.<lang>.mdの両方に反映するため配布更新 |
| `docs/<lang>/readme.txt` | 原稿のリンク・形式・日英の内容を確認。これだけなら`document`も不要 | README.<lang>.txtへの直接コピーなので、理論上は収集・ZIP化だけで足りる。現行では配布更新が必要 |
| `docs/<lang>/images/`の公開画像、`docs/doxyfile`・`footer.html`、`tools/rst2html_*` | `document`。画像・スタイル・参照と変更範囲の表示を確認 | 生成物へのコピー・変換が必要なので配布更新。画像は作者が手動更新する。コピー対象外の`*.pdn`だけを変更し、出力画像が同じなら再生成不要 |
| `extensions/`の公式配布ソース | 開発実行はrepoのソースを参照。対象拡張がReload対象ならReload、確実な確認には再起動。`compile`不要 | library.zip外へソースをコピーするため配布更新。新規ファイルはCOPY_ITEMSと構成検査の収録対象も変更する |
| `samples/_custom.py`・`_commands.json`・`samples/scripts/` | 関連するテンプレート検査。新規の確認用設定で初期配置・明示有効化を確認 | ソースコピーなので`compile`不要、配布更新。`copy`は既存custom.py・commands.jsonを更新しないため、既存設定だけで変更を確認しない |
| `themes/black.ini`・`white.ini`・`gray.ini` | 開発実行で再読込みまたは再起動、関連する配色テスト。`compile`不要 | テーマを直接コピーするため配布更新。画面例を差し替えた場合は`document`も必要 |
| `LICENSE.md`・`licenses/`・`ckit/LICENSE.md`・`pyauto/LICENSE.md` | `document`で取り込んだ条文と原本を検査 | ヘルプと配布原本の両方が変わるので配布更新。単なる原本コピーだけでは不足 |
| `Python315/`の実行依存物、Pythonヘッダー・ライブラリ | [Python更新手順](development.md#既存python環境の更新)に従い、Native Rebuild・`copy`・`compile`。関連テスト | runtime・標準ライブラリ・ネイティブABIに及ぶため配布更新。文書依存の再導入とライセンス確認も行う |
| Docutils・Pygments・Doxygen、`tools/requirements-docs.txt` | 変更後の文書環境で`document` | 文書出力に影響する場合は配布更新。文書用依存だけならPython実行環境の配布内容やC++を変える必要はない |
| `tools/test_*.py`・機能検査スクリプト・Ruff設定 | 該当テスト・静的検査。テスト自体がビルドを行う場合はその手順に従う | アプリ資材を変えなければ配布更新不要。パッケージ検査の修正では既存配布物を使った再検査を優先 |
| `makefile.py`の配布処理 | 工程テストと変更工程の実行。選択基準は[配布資材の確認](release-verification.md#配布資材の確認) | 収録内容・生成・検査を変えた場合は配布更新まで確認。テスト成功だけでは生成物の確認を代替しない |

APIへの影響はコメント変更だけで判定しません。公開クラス・関数の追加削除、名前・引数・グループの変更もヘルプ生成へ影響します。Doxygenの入力範囲は`docs/doxyfile`、追加原稿は`makefile.py`を正とします。

## 現行コマンドと推奨する使い分け

すべてrepoルートのPowerShell 7で実行します。各コマンドが失敗したら、その時点で止めて原因を解消してから次へ進みます。

| 手段 | 実行内容 | 最適な用途 |
|---|---|---|
| `makefile.py compile` | 標準ライブラリと本体・ckit・pyautoを全コンパイルし、Releaseのlibrary.zipを再作成。日英文言を検査 | Python変更のRelease開発確認 |
| `makefile.py copy`／`-d copy` | 選択構成のPython runtime同期、未作成の開発設定配置、sitecustomize.py生成。独自PYDはその構成のビルド結果を保持 | 初回準備、Python依存更新、runtimeの再同期 |
| `makefile.py document` | 日英ヘルプ生成と参照・API等の検査 | 原稿・画像・API説明の短い確認サイクル |
| `makefile.py dist` | 4プロジェクトのRelease Rebuild → compile → copy → document → dist再作成 → 構成・版・日英import等の組込み検査 | ZIPが不要で配布フォルダだけを更新する場合。全生成する |
| `makefile.py release` | distと同じ全生成 → ZIP生成・CRC・SHA256 | **配布フォルダとZIPを更新する通常の推奨手段** |
| `makefile.py all`、引数なし | releaseと同じ | 同じ結果。意図が明確なrelease表記を推奨 |
| `makefile.py archive` | 既存distの構成・版・同梱ヘルプ等を独立検査 → ZIP・CRC・SHA256 | 生成元と一致する配布フォルダが既にあり、ZIPだけを作り直す場合 |
| Visual Studio／MSBuildのBuild | 指定構成のネイティブ増分ビルド | C++変更の開発確認。Python・runtimeコピー・ヘルプ・dist・ZIPは更新しない |

`copy`はヘルプや配布フォルダを更新しません。`compile`は常にRelease用library.zipを生成し、`-d compile`でもDebug用コンパイルにはなりません。`-d`は開発runtimeの`copy`の構成選択に使います。

### Python変更の開発確認

初回は[開発実行と設定](development.md#開発実行と設定)で該当構成を準備します。その後、Python処理だけの変更では以下を選びます。

- Debug: アプリを終了し、編集後のソースで再起動。追加ビルド不要。
- Release: 次を実行してからRelease開発EXEを再起動。

```powershell
.\Python315\tools\python.exe -B makefile.py compile
```

本体・ckit・pyautoの更新を通常のReloadだけで反映しようとしません。Reloadは独自設定・対象拡張の再読込みです。

### C++変更の開発確認

Visual Studioで該当プロジェクトをDebug x64／Release x64のBuildにします。CLIで4プロジェクトを増分ビルドする場合は、同じソリューションを使えます。

```powershell
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$vsPath = & $vswhere -latest -products '*' -version '[18.0,19.0)' -requires Microsoft.Component.MSBuild Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if ($LASTEXITCODE -ne 0 -or -not $vsPath) { throw 'Visual Studio 2026 with C++ tools is required.' }
$msbuild = Join-Path $vsPath 'MSBuild/Current/Bin/MSBuild.exe'
& $msbuild ReCraftLaunch.sln /t:Build /p:Configuration=Debug /p:Platform=x64 /nologo /verbosity:minimal
if ($LASTEXITCODE -ne 0) { throw 'Native Build failed.' }
```

Release開発確認では`Configuration=Release`へ変更します。runtimeが未準備、またはPython依存を更新した場合は続けてDebugなら`makefile.py -d copy`、Releaseなら`makefile.py copy`を実行します。Release用library.zipがなければ`compile`も必要です。準備済みruntimeでC++だけを変えた場合は、毎回のcopy・compileは不要です。

### ヘルプだけの開発確認

```powershell
.\Python315\tools\python.exe -B makefile.py document
```

生成先は`docs/html/ja/`と`docs/html/en/`です。変更したページをブラウザーで確認します。この段階ではdistとZIPは更新されません。配布物まで更新する場合は次のreleaseを使います。

### 配布フォルダとZIPの一括生成

```powershell
.\Python315\tools\python.exe -B makefile.py release
```

生成先は`dist/ReCraftLaunch/`と`dist/ReCraftLaunch_<version>.zip`です。現行では軽微な配布原稿変更でも全工程を実行します。通常は事前のcompile・copy・documentを省き、この1コマンドに任せるのが最短です。先に原稿のエラーを切り分けたい場合だけdocumentを先行させますが、release内では再度生成されます。

ZIPを使わない確認ならmakefile.py distで止めます。ただし既存の同版ZIPは更新されないため、更新したdistと古いZIPを取り違えないようにします。最終的にZIPも必要なら、最初からreleaseを使うと直前の検査成功を引き継ぎ、単独archiveの独立検査を重ねずに済みます。

### 既存の配布フォルダからZIPだけを再作成

```powershell
.\Python315\tools\python.exe -B makefile.py archive
```

これはソース変更の反映手段ではありません。Python・原稿・画像等を編集したままarchiveだけを実行してもdistは更新されません。構成・版・文言等の検査が通っても、本体の全pycやヘルプ本文が最新ソース由来である保証にはなりません。単独archiveは配布importスモークや機能テストを再実行しません。

同版ZIPは上書きされます。ソース・資材・条件が変わらず、検査済みZIPも残っていれば、作り直さずその成果物を使います。

## 配布生成の方針

配布フォルダとZIPの通常の更新はreleaseの1コマンドへ揃えます。distは同じ全生成のうちZIP化だけを省く入口で、別の高速生成方式ではありません。全生成をall／release／distで共用するため、配布内容・安全検査・失敗時の停止を別々に保守しません。

開発中はcompile・copy・document・Native Buildを目的に応じて使います。配布時は、既存EXE・PYDの鮮度を別記録で追跡せず、4プロジェクトを必ずRelease Rebuildします。Pythonと日英ヘルプも毎回生成し、配布フォルダを作り直して検査します。当面は高速化や自動差分判定を扱いません。

## 共通の注意

- `makefile.py clean`はbuild・dist・生成ヘルプ全体を削除し、build/run内の開発設定も失われるため、通常の修正・局所整理には使いません。
- distは生成専用です。原稿・ソースを直し、dist内のHTML・pyc・READMEだけを編集して完了させません。
- 言語非依存の機能は重複検査せず、文言・画像・配置を変えた範囲だけ言語別の表示確認を追加します。組込み検査の成功だけを実IME・UAC・ブラウザー可視品質の確認とは扱いません。
- 生成・ZIP化と、GitHubへの反映・Release添付・公開は別工程です。
