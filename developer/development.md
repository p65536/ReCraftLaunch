# ReCraftLaunchの開発環境

この文書は現行のビルド・開発・言語選択・配布手順の正本です。コマンドは取得したソースのリポジトリルートで実行します。設計と仕様上の制約は[アーキテクチャ](architecture.md)、再利用する確認方法は[配布版の確認手順](release-verification.md)、文書生成の詳細は[文書生成環境](../tools/README-docs.md)を参照してください。

変更したファイルから必要な生成工程を選ぶ場合は、[変更内容別のビルド・パッケージ手順](build-workflow.md)を参照してください。開発確認に必要な個別工程と、常に全生成する配布更新を区別して説明しています。

ビルド対象はx64のみです。Debug x64／Release x64を使用します。
Python 3.15.2 x64、Visual Studio 2026のPlatform Toolset v145、Windows SDK 10.0.26100.0を使用します。
`makefile.py dist` は4プロジェクトをRelease x64でビルドします。
PowerShellスクリプトはPowerShell 7で実行します。
Visual Studio Installerで「C++によるデスクトップ開発」（MSVC v145 x64/x86、Windows SDK）を導入します。
配布スクリプトはVS 2026のMSBuildを選択します。配布先には最新のVisual C++ v14 Redistributable（x64）が必要です。
VCランタイムはビルドに使ったMSVCと同じか新しいバージョンを使用します。

## 初回clone後の環境構築

Python 3.15.2 x64のNuGetパッケージを、リポジトリルートの`Python315/`へ展開します。パッケージ内の`tools/`構造を維持し、`Python315/tools/python.exe`等を使用します。
次のコマンドをPowerShell 7で実行します。既存の`Python315/`がある場合は、取得・展開前に停止します。

```powershell
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath 'Python315') {
    throw 'Python315 が既に存在します。既存の環境は上書きしません。'
}
$pythonPackage = Join-Path ([IO.Path]::GetTempPath()) ('python.3.15.2-' + [guid]::NewGuid() + '.nupkg')
try {
    Invoke-WebRequest -Uri 'https://api.nuget.org/v3-flatcontainer/python/3.15.2/python.3.15.2.nupkg' -OutFile $pythonPackage
    [IO.Compression.ZipFile]::ExtractToDirectory($pythonPackage, (Join-Path (Get-Location).Path 'Python315'))
}
finally {
    Remove-Item -LiteralPath $pythonPackage -Force -ErrorAction SilentlyContinue
}

foreach ($path in @('python.exe', 'include/Python.h', 'libs/python315.lib', 'python315.dll')) {
    if (-not (Test-Path -LiteralPath (Join-Path 'Python315/tools' $path) -PathType Leaf)) {
        throw "Pythonの必須ファイルがありません: $path"
    }
}
.\Python315\tools\python.exe -B -c "import struct, sys; print(sys.version); print(struct.calcsize('P') * 8, 'bit'); sys.exit(sys.version_info[:3] != (3, 15, 2) or struct.calcsize('P') != 8)"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.15.2 x64が必要です。' }
```

Pythonの確認後、[文書生成環境の導入手順](../tools/README-docs.md#導入)に従い、`tools/requirements-docs.txt`を使ってDocutils・Pygmentsを導入し、Doxygenを配置します。その後、[開発実行と設定](#開発実行と設定)または配布作成の手順へ進みます。
Pythonと文書生成ツールの実体はGit管理外です。

## 既存Python環境の更新

3.15系のパッチ更新でも、旧環境へファイルを上書きせず、検証したNuGetパッケージ全体へ切り替えます。以下は3.15.2 x64への更新例です。次のパッチ更新では`$pythonVersion`と検証用の版タプルを合わせて変更し、ライセンスも取得版と比較してください。`Python315/tools/`・`python315.dll`・`python315.lib`の名前は維持します。

ReCraftLaunch、同梱Pythonを使う端末・IDEの処理を終了してから、リポジトリルートのPowerShell 7で実行します。既存の追加パッケージは最初に一覧を確認し、必要性を判断します。`site-packages`や`Scripts`、生成済みEXE・DLL・PYDはコピーしません。文書依存は切り替え後に再導入し、既存の`third_party/doxygen/`はそのまま使います。

```powershell
$ErrorActionPreference = 'Stop'
$pythonVersion = '3.15.2'
$repoRoot = (Get-Location).Path
$pythonDir = Join-Path $repoRoot 'Python315'
$buildDir = Join-Path $repoRoot 'build'
if (-not (Test-Path -LiteralPath (Join-Path $repoRoot 'ReCraftLaunch.vcxproj') -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $pythonDir 'tools/python.exe') -PathType Leaf)) {
    throw '既存Python315のあるリポジトリルートで実行してください。'
}
foreach ($path in @($pythonDir, $buildDir)) {
    if ((Test-Path -LiteralPath $path) -and
        ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "更新対象にjunctionやsymlinkは使用できません: $path"
    }
}
& (Join-Path $pythonDir 'tools/python.exe') -B -m pip list
if ($LASTEXITCODE -ne 0) { throw '既存パッケージの確認に失敗しました。' }

# 一意な作業先と退避先を同じドライブのGit管理外build/に確保する。
$pythonUpdate = Join-Path $buildDir ('python-update-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $pythonUpdate | Out-Null
$pythonPackage = Join-Path $pythonUpdate "python.$pythonVersion.nupkg"
$pythonStaged = Join-Path $pythonUpdate 'new'
$pythonBackup = Join-Path $pythonUpdate 'previous'
Write-Host "更新作業先（復旧用に控える）: $pythonUpdate"
Invoke-WebRequest -Uri "https://api.nuget.org/v3-flatcontainer/python/$pythonVersion/python.$pythonVersion.nupkg" -OutFile $pythonPackage
[IO.Compression.ZipFile]::ExtractToDirectory($pythonPackage, $pythonStaged)
foreach ($path in @('python.exe', 'include/Python.h', 'libs/python315.lib', 'python315.dll')) {
    if (-not (Test-Path -LiteralPath (Join-Path "$pythonStaged/tools" $path) -PathType Leaf)) {
        throw "Pythonの必須ファイルがありません: $path"
    }
}
$pythonCheck = "import struct, sys; print(sys.version); print(struct.calcsize('P') * 8, 'bit'); sys.exit(sys.version_info[:3] != (3, 15, 2) or struct.calcsize('P') != 8)"
& (Join-Path $pythonStaged 'tools/python.exe') -I -B -c $pythonCheck
if ($LASTEXITCODE -ne 0) { throw 'Python 3.15.2 x64が必要です。切り替えは行いません。' }

$oldMoved = $false
try {
    Move-Item -LiteralPath $pythonDir -Destination $pythonBackup
    $oldMoved = $true
    Move-Item -LiteralPath $pythonStaged -Destination $pythonDir
    & (Join-Path $pythonDir 'tools/python.exe') -I -B -c $pythonCheck
    if ($LASTEXITCODE -ne 0) { throw '切り替え後のPython検証に失敗しました。' }
    & (Join-Path $pythonDir 'tools/python.exe') -B -m pip install -r tools/requirements-docs.txt
    if ($LASTEXITCODE -ne 0) { throw '文書生成依存の再導入に失敗しました。' }
    & (Join-Path $pythonDir 'tools/python.exe') -B -c "import docutils, pygments; print(docutils.__version__, pygments.__version__)"
    if ($LASTEXITCODE -ne 0) { throw '文書生成依存のimportに失敗しました。' }
}
catch {
    if ($oldMoved) {
        if (Test-Path -LiteralPath $pythonDir) {
            Move-Item -LiteralPath $pythonDir -Destination (Join-Path $pythonUpdate 'failed')
        }
        Move-Item -LiteralPath $pythonBackup -Destination $pythonDir
    }
    throw
}
Write-Host "旧環境の退避先: $pythonBackup"
```

取得・展開・事前検証の失敗では旧環境を変更しません。切り替え・文書依存の再導入中に失敗した場合は、上の`catch`で旧環境を戻します。失敗した新環境も削除せず`failed/`へ残します。復旧の移動自体が失敗した場合は、使用中のプロセスを終了し、表示した作業先と`Python315/`の状態を確認してください。

切り替え成功後に戻す場合は、同じPowerShellセッションで以下を実行します。別セッションでは`$pythonUpdate`に上で表示された作業先の絶対パスを設定し直します。退避先を確認してから移動し、新旧どちらも上書き・削除しません。

```powershell
$ErrorActionPreference = 'Stop'
$repoRoot = (Get-Location).Path
$pythonUpdate = [IO.Path]::GetFullPath($pythonUpdate)
$buildPrefix = [IO.Path]::GetFullPath((Join-Path $repoRoot 'build')) + [IO.Path]::DirectorySeparatorChar
if (-not $pythonUpdate.StartsWith($buildPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw '退避先はこのリポジトリのbuild/内である必要があります。'
}
$pythonDir = Join-Path $repoRoot 'Python315'
$pythonBackup = Join-Path $pythonUpdate 'previous'
if (-not (Test-Path -LiteralPath (Join-Path $pythonBackup 'tools/python.exe') -PathType Leaf)) {
    throw '旧環境の退避先がありません。移動は行いません。'
}
$pythonFailed = Join-Path $pythonUpdate ('reverted-' + [guid]::NewGuid())
Move-Item -LiteralPath $pythonDir -Destination $pythonFailed
try {
    Move-Item -LiteralPath $pythonBackup -Destination $pythonDir
}
catch {
    Move-Item -LiteralPath $pythonFailed -Destination $pythonDir
    throw
}
& (Join-Path $pythonDir 'tools/python.exe') -I -B -c "import struct, sys; print(sys.version); print(struct.calcsize('P') * 8, 'bit')"
if ($LASTEXITCODE -ne 0) { throw '復旧したPythonの実行確認に失敗しました。' }
```

更新後は4つのネイティブプロジェクトをRelease x64で**リビルド**し、[Python更新時の検証](release-verification.md#python更新時の検証)と`makefile.py release`で日英配布物を再生成します。通常の差分ビルドだけでは、新パッケージのヘッダー等の日時が既存中間ファイルより古い場合に再コンパイルされないことがあります。復旧時も旧Pythonでリビルド・配布再生成し、DLL・PYD・バイトコードを同じ環境に揃えます。`makefile.py clean`は設定と退避先を含む`build/`全体を削除するため、更新・復旧の整理には使いません。退避先は実機確認を終えるまで保持し、削除する場合も表示された一意の作業先だけを対象にしてください。

## 改行と文字コード

管理対象のテキストはLFで保存します。`.gitattributes`の`* text=auto eol=lf`で、Gitがテキストと判定したファイルのGit内・チェックアウト時の改行をLFに揃えます。ライセンスも本文・文字コードを維持してLFに揃えます。
`clnch/clnch.rc`と`clnch/resource.h`はUTF-16LE・BOM・CRLFを維持します。Gitは両ファイルをバイナリ扱いするため改行変換しません。
一般テキストの改行はエディター側でLFを設定します。VSCodeでは`"files.eol": "\n"`を使います。`.editorconfig`には文字コードと上記2ファイルのCRLF例外を定義し、次のコマンドで検査します。

```powershell
.\Python315\tools\python.exe -B tools/check_text_format.py
```

基本はUTF-8 BOMなしです。Python・JSON・Markdown・PowerShellもこれに従います。
C/C++とVisual Studioのプロジェクト・ソリューションはUTF-8 BOMあり、`clnch/clnch.rc`・`clnch/resource.h`はUTF-16LE BOMありを使います。
外部由来の`licenses/`は元の文字コードを維持します。バイナリ、Git管理外の依存・生成物・個人設定は一括変換の対象にしません。

## Ruffの除外と新規診断

初回は[Python環境の構築](#初回clone後の環境構築)を済ませ、同じPythonへ開発用のRuffを導入します。Ruffは配布物には含めません。

```powershell
.\Python315\tools\python.exe -B -m pip install ruff
```

公開APIの再公開、遅延import、隔離テスト等で必要な診断の除外は、理由付きの行単位`# noqa: ルール番号  # 理由`で指定しています。
次のコマンドはPATHの設定を必要としません。

```powershell
.\Python315\tools\python.exe -B -m ruff check --no-cache --no-fix .
.\Python315\tools\python.exe -B -m ruff check --no-cache --no-fix --ignore-noqa .
```

通常検査は診断0件・終了コード0を確認します。除外監査は意図した診断も含めて表示するため、終了コード1自体を新しい不具合とみなしません。RUF100は不要なnoqa、PGH004はルール番号のない一括noqaを検出します。除外理由の妥当性は、対象コードと併せて確認します。

新規の除外・既存注記の対象行・ruff.tomlのignore、per-file-ignores、対象除外、選択ルールの変更は差分で理由を確認します。同じ行・同じルールの新しい問題は既存注記に隠れる可能性があります。Ruff更新時も通常検査と除外監査を使い、不要な注記を整理します。

検証スクリプトと確認項目は[確認手順](release-verification.md#自動検証の選択)を参照してください。

## 開発実行と設定

開発用の実行環境は、常用環境とは別のフォルダで使用してください。以下の<構成>はDebugまたはReleaseです。各構成のsettings/は独立し、ビルド・コピーで既存内容を上書きしません。

開発実行には `build/run/x64/Release/reclnch.exe`（Release）または `build/run/x64/Debug/reclnch_d.exe`（Debug）を使用します。
初回は4つのC++プロジェクトを使用する構成でビルドし、Releaseは `makefile.py compile` と `makefile.py copy`、Debugは `makefile.py -d copy` を実行します。`compile`はRelease用library.zipを生成します。
[ReCraftLaunch.sln](../ReCraftLaunch.sln) から `ReCraftLaunch`・`clnch_native`・`ckitcore`・`pyautocore` をDebug x64／Release x64でビルドできます。ソリューションのビルドだけではPythonのコンパイル・コピーや文書生成は行いません。
`makefile.py dist` は正式な配布作成手順で、4プロジェクトをReleaseでRebuildし、Python・文書・配布物の準備をまとめて行います。配布時は既存のEXE・独自PYDを増分ビルドの結果として再利用しません。通常の開発ではソリューションの増分Buildを引き続き使えます。

`makefile.py copy`（Release）／`makefile.py -d copy`（Debug）が生成する `build/run/x64/<構成>/sitecustomize.py` により、開発実行用のパスを設定します。
標準実装は `clnch/` 内に置きます。`clnch_standard`が構成とGUI入口、`clnch_commandregistry`が登録・解決・再構築、`clnch_commandexecutor`が実行、`clnch_commandplatform`がWindows連携を担当します。編集・一覧・JSON管理は `clnch_cmdeditor`・`clnch_cmdlist`・`clnch_cmdstore` です。Release実行・配布では `library.zip`、Debug実行ではrepoのPythonソースを使用します。
開発実行の既定の保存先は `build/run/x64/<構成>/settings/` で、サンプルから生成した `custom.py`・`commands.json` を使用します。
保存先の選択は開発用exe隣の `build/run/x64/<構成>/reclnch_exe.ini` を参照します。マルチユーザーをONにすると通常実行と同じAppDataフォルダを使用するため、個人設定を使わない検証ではOFFのままにします。
テーマと拡張機能はリポジトリの `themes/`、`extensions/` を参照します。`sitecustomize.py`の資源ルート指定は維持し、`clnch_main`で選択した設定保存先の`scripts/`を作成・検索パス追加します。既定は`build/run/x64/<構成>/settings/scripts/`、AppData指定時は`%APPDATA%/ReCraftLaunch/scripts/`です。

`makefile.py copy` と `makefile.py dist` は、次の開発用ファイルが未作成の場合だけサンプルから配置します。

- `samples/_custom.py` → `build/run/x64/<構成>/settings/custom.py`
- `samples/_commands.json` → `build/run/x64/<構成>/settings/commands.json`

既存の`custom.py`・`commands.json`・`scripts/`の内容は保持します。`scripts/`は未作成なら空で作成します。新しいテンプレートを試す場合は、自分で既存設定の内容を確認して反映してください。

公式サンプルの実装は`extensions/stamp.py`・`netdrive.py`・`clock.py`・`completion_keys.py`・`list_keys.py`です。配布ではmakefile.pyの単一COPY_ITEMSに列挙したソースだけを`extensions/`へコピーし、個人用・任意の追加モジュールは取り込みません。`samples/scripts/.gitkeep`で配布ZIPの`settings/scripts/`を保持します。`.gitkeep`は実行処理に関与しません。拡張の検索順・Reload契約は[設計](architecture.md#設定と登録の境界)、使用例は[利用者マニュアル](../docs/ja/index.txt)を参照してください。

修飾キーの共通既定動作は `clnch_modifierconfig.py` がINI `[MODIFIER]` を読込み、`clnch_configmenu.py` から変更・保存します。
`MainWindow.modifier_settings` を実行時に参照するため、メニュー変更に個人フックの再適用は不要です。共通の置換元一覧は順序を保持し、置換先は修飾キーごとです。
詳細な設定形式は `docs/ja/commands.md` を参照してください。
C++ビルドだけ、または `makefile.py compile` だけでは上書きされません。サンプルへの書き戻しも行いません。

## 開発用INIの管理と初期化

ビルド処理は `build/run/x64/<構成>/settings/reclnch.ini` を自動で初期化しません。
INIには入力設定、ウィンドウ位置、フォント、テーマなどの状態が保存されます。
コマンド登録はJSONで管理し、`[COMMANDLIST]` は使用しません。
再ビルドだけでは完全な初期状態には戻りません。

INIを含めてサンプル設定へ戻す場合は、アプリを終了してから
`build/run/x64/<構成>/settings/reclnch.ini` を削除してください。custom.py・commands.jsonも初期化する場合は内容を確認して削除し、`makefile.py copy` または `makefile.py dist` で未作成のファイルを配置してください。

`makefile.py clean` は `build/`・`dist/`・生成文書を削除するため、開発用の設定や配布物も削除します。
その後はC++ビルドとPythonのコンパイル・コピーが必要です。

## 構成別の出力と検査

- 実行環境: `build/run/x64/<構成>/`。EXEとPython DLLを直下、3つの独自PYDと標準DLL・PYDをlib/へ配置します。PYDはネイティブビルドからlib/へ直接出力し、copyは別構成のPYDをコピーしません。copyはこの3ファイルを保持し、現在のPython同梱DLL・PYDを上書きして、それ以外のlib/直下の通常ファイルを除去します。lib/の子ディレクトリ、コピー対象・祖先のリンク／リパースポイントは削除せずエラーにします。
- 中間出力: `build/obj/<project>/x64/<構成>/`。obj・tlog・lib・exp・pdb等を集約し、ソース側へ生成しません。
- Releaseの自作EXE・PYDは `/PDBALTPATH:%_PDB%` でPE内のPDB参照をファイル名だけにします。PDB本体は上記の中間出力先へ生成します。Releaseをデバッグする場合は、Visual Studioのシンボル設定で対応するPDBの場所を指定します。
- バイトコード作業先: `build/Lib/`。Release専用で、Debugはソースを読みます。
- 配布元: `build/run/x64/Release/`のみ。dist/ReCraftLaunchの構造は変えず、lib/の余剰・欠損、Python同梱バイナリとの内容不一致、直下の余剰バイナリ、Debug CRTや別Python DLLへの依存を配布作成とarchiveで拒否します。Python315/toolsは検証時にも必要です。配布のRebuild・削除前には管理出力の内部のリパースポイントも拒否します。

同じソース・依存物から得る配布ファイル構成を検証対象とします。MSVCのPEタイムスタンプやZIPのメタデータを固定する処理は行わず、配布ZIP全体のバイト単位の再現性は保証しません。開発用settings/と配布の利用者環境は同期・削除の対象外です。dist/ReCraftLaunchは従来どおり配布生成専用で毎回再作成します。

構成切替の増分ビルドは `pwsh -NoProfile -File tools/check_build_isolation.ps1` で検査します。Release→Debug→Releaseの順にビルドし、他構成のEXE・PYDが変わらないことをSHA256で確認します。

ソースからのネイティブテストは `RECRAFT_TEST_CONFIGURATION` 環境変数でDebug／Releaseを選びます。省略時はReleaseです。tools/native_test_support.pyが対象のlib/へ読込先を固定し、欠損時に他構成やソース側PYDへフォールバックしません。実読込先・CRTとDebug混入拒否はtools/test_native_build.pyで確認します。

```powershell
$env:RECRAFT_TEST_CONFIGURATION = 'Debug'
.\Python315\tools\python.exe -B tools/test_native_build.py
.\Python315\tools\python.exe -B tools/test_window_show.py
Remove-Item Env:RECRAFT_TEST_CONFIGURATION
```

## Pythonのコンパイル

リポジトリルートで `Python315/tools/python.exe -B makefile.py compile` を実行します。
毎回 `build/Lib/` を削除してバイトコードを再生成し、`build/run/x64/Release/library.zip` を作成します。
この処理は `build/run/x64/<構成>/settings/reclnch.ini` や開発用設定を初期化しません。

編集・ドロップ・キー操作は [操作リファレンス](../docs/ja/commands.md)、JSONの構造は [commands.jsonの形式](../docs/ja/command_json.txt) を参照してください。

ZIPにはPython標準ライブラリ、標準コマンドと編集・一覧・保存処理を含むReCraftLaunch本体、ckit、pyautoを含めます。
個人設定・サンプル設定、ckitのテスト、pyautoのサンプル・文書・ツール、ビルド用スクリプトは含めません。
文書生成用のDocutils・PygmentsもZIPには含めません。

## 表示言語の選択

日本語・英語の文言とヘルプを同じ配布物へ収録します。Config →「言語」（英語UIではLanguage）で「Japanese」／「English」を選択し、終了して再起動すると反映します。Debugはソース、Releaseはlibrary.zipを参照し、どちらも同じ設定で選択できます。言語変更のための再ビルドは不要です。

選択した保存先のreclnch.iniの`[MISC] language = ja`／`en`を起動時に読みます。未設定・不正値は英語で起動し、不正な保存値は自動修正しません。Configは変更時だけ既存のINI保存処理を呼び、再起動を案内します。現在の言語と次回起動用の言語が異なる場合は両方を表示します。Reloadでは言語を変更しません。

clnch_strings_ja.pyとclnch_strings_en.pyは文字列定数だけを持ち、clnch_strings.pyが日本語を静的に公開します。起動時に選択言語の定数を窓口へ適用し、定義モジュール自体は変更しません。既存の`import clnch_strings as strings`と属性参照を維持します。詳細は[文言供給と配置の設計](architecture.md#文言と言語選択)を参照してください。

`makefile.py compile`は窓口・日英定義を同じlibrary.zipへ収録します。公式配布を言語別に生成する`--lang`・`-Lang`・`-Both`は廃止しました。

### バージョン番号

番号の正本は`clnch/clnch_resource.py`の`clnch_version`だけです。`X.Y.Z`の3要素を使い、各要素は0～65535の整数とします。アプリ表示・ZIP名・ヘルプ・Windowsの文字列版は同じ番号、Windowsの数値版は`X,Y,Z,0`です。不正な形式・範囲は生成前にエラーになります。

ReCraftLaunch.vcxprojのCustomBuildが、Debug／Releaseそれぞれの`$(IntDir)`に`recraft_version.h`を生成します。clnch.rcはそのマクロを参照します。正本と生成処理の依存関係を追跡し、生成内容が同一ならヘッダーのタイムスタンプを変えません。ヘッダーはGit管理・配布の対象外です。

`makefile.py document`は日英index.txtの`{{APP_VERSION}}`だけを置換した原稿を`docs/obj/<lang>/index.txt`に生成し、DoxygenのPROJECT_NUMBERも正本から設定します。原稿単体のプレビューには置換前のトークンが表示されます。

配布作成と`archive`は、正本・配布EXE・library.zip内の番号を照合します。EXEでは数値版・文字列版・製品名・元ファイル名・Debugフラグも確認します。library.zipは隔離プロセスで読み込みます。不一致時はZIP作成・上書き前に停止するため、番号を更新した後は先に配布物を再生成してください。MSBuildだけではRelease用library.zipやヘルプを更新しません。

### 文言編集と検証

文言は`clnch/clnch_strings_ja.py`・`clnch/clnch_strings_en.py`で編集します。定数名・名前付きプレースホルダー・アクセスキー・CLOCK_FORMATのstrftime書式を保持してください。説明本文は`\n`で改行でき、項目ラベルとタイトルは1行にします。識別子、JSON／INIのキー・値、コマンド名、IPC入力は翻訳しません。

```powershell
.\Python315\tools\python.exe -B tools/test_strings.py
.\Python315\tools\python.exe -B tools/test_config_menu.py
.\Python315\tools\python.exe -B tools/test_variable_layout.py
.\Python315\tools\python.exe -B makefile.py compile
.\Python315\tools\python.exe -B tools/check_language.py --library build/run/x64/Release/library.zip
```

文言を編集した場合は再コンパイル・再起動します。言語の選択だけなら再ビルドは不要です。OS言語の自動判定、外部言語ファイル、実行中の切替はありません。OSのシェルメニュー・システムボタン、例外詳細・開発診断、個人拡張の文言は対象外です。

通常起動は保存先決定→INI読込→clnch_strings.initialize→clnch_text.initialize→GUI本体import→MainWindow生成の順です。clnch_textがckitへ12種類の文言を供給し、GUIモジュールがimport時に保持する辞書・リストも選択言語になります。既存インスタンスへのIPC送信だけの経路はINI・GUI本体を読みません。ckitから本体への逆importはありません。ckitの直接利用入口も、ウィジェット・設定フックの利用前に文言を供給します。

`test_language_startup.py`は保存先2通り、ソース／配布ZIP、日英・未設定・不正値とIPC軽量経路を隔離プロセスで確認します。`test_strings.py`は定数名・プレースホルダー、同じlibrary.zipからの日英選択、12種類のckit文言、配布工程と単一ZIPを検査します。配布検査は日英両方の文書・版・importを確認します。

編集画面はラベル幅から入力列を決め、入りきらないラベルは入力欄の上へ折り返します。択一欄は横配置から縦配置へ切り替わります。説明候補の最大行数を予約し、入力中・Modifier切替中に画面を伸縮させません。高さが足りない編集・フォルダ画面はホイール／PageUp・PageDownでスクロールし、入力欄へ移ると自動で表示位置を合わせます。編集最下部のキーガイドは実測して右寄せ、説明・Configのヘルパーテキストは左寄せを維持します。一覧の最大幅は上限で、短い項目では内容幅に縮みます。項目とヒントを折り返し、既存の選択・検索・スクロールを維持します。確認画面はボタンの幅・行数を確保し、本文だけをスクロールします。

配置検査の基準は作業領域1024×768、MS Gothic 12、DPI 100%／150%／200%相当です。1.5〜2倍程度の仮翻訳、全角・改行・長い単語を試します。DPI変更・画面構成／作業領域通知、異なる作業領域への移動で再配置します。非表示Windowsネイティブウィンドウでの座標検査は、実際の描画・ドラッグ・IME入力・モニター間移動の実機確認を代替しません。右から左への表示・複雑な組版・任意の長さ／極端に小さい画面は保証範囲外です。

## 同梱のローカルヘルプとF1

配布ZIPには日英ヘルプを同梱し、メイン・コンソールのF1でアプリ隣のdocs/ja/index.htmlまたはdocs/en/index.htmlを現在適用中の言語で開きます。再起動前の保存値には追従しません。配置・非同期処理・表示状態の設計は[ヘルプとコンソール](architecture.md#ヘルプとコンソール)、ブラウザーとF1の確認は[確認手順](release-verification.md#同梱ヘルプ)を参照してください。

### ヘルプ同梱ZIPの生成

```powershell
.\Python315\tools\python.exe -B makefile.py release
# allも同じ単一配布とZIPを生成
.\Python315\tools\python.exe -B makefile.py all
```

release／allはmakefile.py内の共通処理で、4プロジェクトをRelease x64でRebuildします。日英文言入りlibrary.zipのcompile、開発用runtimeのcopy、日英documentを各1回実行し、単一のdist/ReCraftLaunchへ収録します。文書生成はHTML・CSS・JavaScript・画像・API文書・操作一覧・ライセンスをdocs/html/ja・enへ生成し、配布先docs/ja・enにも全体をコピーし、検査済み生成物とのファイル集合・内容の一致を確認します。事前に文書生成ツールを[準備](../tools/README-docs.md)してください。

配布処理は文言定義・ソースとpyc・日英ヘルプ・README・COMMANDS・正本／EXE／library.zipの版と、隔離した配布importを検査します。失敗時は停止します。all／releaseのarchiveは直前の配布検査成功を引き継ぎ、単一の`ReCraftLaunch_<version>.zip`を生成してCRCとSHA256を確認します。archiveの単独実行は配布フォルダの構成・ネイティブ・版・文言・日英ヘルプを独立検査します。検査の責務・選択は[配布資材の確認](release-verification.md#配布資材の確認)を参照してください。

未作成の開発設定だけをサンプルから配置し、既存custom.py・commands.json・scripts/を保持します。dist/ReCraftLaunchは再作成します。同じ版のZIPは上書きされるため、実機確認後に生成元が変わらなければ、そのZIPと結果を再利用できます。

## 独自設定のサンプル

独自定義ファイルはcustom.py、配布サンプルはsettings/_custom.py、サンプルの原稿はsamples/_custom.pyです。

stampの例は現在日時をクリップボードへコピーし、strftimeの書式を変更できます。Alt+Enterの引渡し先は独自定義ではなくConfigとINI [ALT_ENTER]で管理します。サンプルはすべてコメント状態で、コピーしただけでは追加処理を実行しません。必要な行の先頭の「#」だけを外し、続く半角スペース4個を残します。configure／configure_ListWindowをそれぞれ1つへまとめて使います。

NetDriveを有効にする場合は同名のJSON登録を併用しません。標準入力・修飾キー設定をPythonで二重管理しない方針は維持します。custom.pyから明示importしたextensions/のPythonソースもReloadで再読込します。
NetDriveの使い方案内と成功通知は、UI言語にかかわらず英語で表示します。

## ドキュメント生成

repo内の同梱PythonにDocutils・Pygmentsを導入し、`third_party/doxygen/bin/` にDoxygenを配置します。
導入バージョンと手順は [ドキュメント生成環境](../tools/README-docs.md) を参照してください。

リポジトリルートで次のコマンドを実行します。

```powershell
.\Python315\tools\python.exe -B makefile.py document
```

`docs/obj/` と `docs/html/` の日英両方の出力を再生成します。<lang>はjaまたはenです。生成結果は `docs/html/<lang>/index.html` で確認します。
出力はGit管理外です。検査スクリプトはローカル参照先・HTMLアンカー・画像と共通CSSのコピー・未使用の文書画像を確認し、ブラウザー表示やJavaScript動作は検証しません。
文書画像は言語別に `docs/<lang>/images/` に置き、ファイル名は小文字のsnake_caseで `<分類>_<画面・機能>[_<詳細>].png` とします。画面階層は左から右へ並べ、同じ画面の派生例は末尾で区別します。連番・撮影日時は付けません。

| 分類 | 対象 | 命名例 |
|---|---|---|
| `app_` | 製品の画像資材 | `app_icon.png` |
| `launcher_` | メイン画面の入力・表示・補完 | `launcher_main.png`、`launcher_completion_commands.png` |
| `command_` | コマンドの一覧・編集 | `command_list.png`、`command_edit_modifier.png` |
| `config_` | 設定メニューとその配下 | `config_menu.png`、`config_alt_enter_action.png`、`config_alt_enter_application.png`、`config_alt_enter_web.png` |
| `console_` | コンソールの表示 | `console_about.png` |

スクリーンショットは `docs/<lang>/index.txt` の対応する説明から参照します。画面例で変更した設定はキャプションへ明記し、削除済み機能の画像は残しません。改名時は本文、`docs/doxyfile`のロゴ指定、文書生成テストの参照も更新し、文書・配布先を再生成して旧名を残さないようにします。
RSTの本文断片は `.rst-content` で囲み、配色はDoxygenのテーマへ統一します。追加CSSは `HTML_EXTRA_STYLESHEET` で読み込み、本文内の画像を幅に合わせて縮小します。ヘッダーのロゴだけは `#projectlogo img` へ48px角の寸法を指定します。
このMarkdownはHTML生成対象に含まれません。

`makefile.py dist` は文書を生成・検査し、docs/html/<lang>の一式を配布先docs/<lang>へ同梱します。

## 配布とアーカイブ

`Python315/tools/python.exe -B makefile.py dist` は `dist/ReCraftLaunch/` を再作成します。
配布内容はmakefile.pyの単一 `COPY_ITEMS` が正です。個人設定、新旧INI、VCランタイムDLLは含めません。生成HTMLはdocs/ja・docs/enへ同梱します。
配布用の短い案内は `docs/<lang>/readme.txt` を原稿とし、日英両方を配布ルートの `README.ja.txt`・`README.en.txt` へそのままコピーします。操作原稿も `COMMANDS.ja.md`・`COMMANDS.en.md` として同梱し、旧README.txt・COMMANDS.mdは配布しません。詳しい操作・設定は同梱ヘルプで説明します。
`makefile.py release` はdistと同じ全生成の後にZIPを作成し、`makefile.py archive` は生成済み配布フォルダから
`dist/ReCraftLaunch_<version>.zip` を作成します。`makefile.py all` は文書生成を含む配布作成・アーカイブを実行します。

通常実行のデータ保存先はアプリ内の `settings/` が既定です。Config →「設定の保存先」で「アプリフォルダ」／「AppDataフォルダ」（`%APPDATA%/ReCraftLaunch/`）を選択します。
指定はexe隣の `reclnch_exe.ini` の `[DATA] multi_user = 0` または `1` に保存します。初回起動時にファイルがなければ `multi_user = 0` で作成し、既存ファイルは上書きしません。項目省略時も0です。書込みは一時ファイルを閉じてから同じフォルダ内で置換し、失敗した場合は元の指定を維持します。
「アプリフォルダ」は `<アプリ>/settings/`、「AppDataフォルダ」は `%APPDATA%/ReCraftLaunch/` を参照します。サンプルは配布先の `settings/_custom.py`・`settings/_commands.json` に配置します。
設定を反映するにはReCraftLaunchを再起動してください。再起動後は切替先の `reclnch.ini`・`commands.json`・`custom.py` を使用します。設定ファイルの自動移動・コピーや旧ルートへのフォールバックは行いません。コマンドの相対パス解釈は変更しません。引き継ぐ場合は終了後に手動でコピーしてください。
`reclnch_exe.ini` は利用者設定なので配布にもZIPにも含めず、ビルドでも初期化しません。旧ルートの `config.py` と `extension/cmd_*.py` は現行コアとしては読み込みません。
INI名は `reclnch.ini` です。アプリは旧 `clnch.ini` を読み込まず、旧INIや `%APPDATA%/CraftLaunch/` を自動移行・変更・削除しません。
ウィンドウクラスは ReClnchWindowClass です。ckitの共通処理により、トレイアイコン用の ReClnchTaskTrayWindowClass も登録されますが、現行のReCraftLaunchではトレイアイコン機能を使用していません。
別コピーのReCraftLaunchは既存インスタンスへIPCを送ります。CraftLaunchとは独立して起動します。

## 配布依存の除外

`libtommath.dll` と `python.cat` は開発用実行環境・配布物へのコピーから除外します。`Python315/tools/DLLs/` の元ファイルは保持します。

## 画像テーマ・壁紙の廃止

画像装飾・壁紙とPillow依存は廃止し、配色テーマと汎用画像APIは維持します。削除API・互換性・描画の制約は[配色と描画](architecture.md#配色と描画)、確認方法は[描画とフォント](release-verification.md#描画とフォント)を参照してください。
