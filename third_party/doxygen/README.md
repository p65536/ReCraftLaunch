# Doxygen for documentation builds

- Version: 1.18.0 (Windows x64)
- Official downloads: https://www.doxygen.nl/download.html
- Archive: https://www.doxygen.nl/files/doxygen-1.18.0.windows.x64.bin.zip
- Archive SHA256: `e84f54cfd49ef06b0b16536056dbec0c496323de28abcce53a4269463de35eaf`
- License: https://www.doxygen.nl/license.html

Keep `doxygen.exe` and `libclang.dll` from this archive in `bin/` beside this
file. The archive and extracted binaries are local tools excluded from Git,
like the bundled `Python315/` runtime. No system installation or PATH change
is required.

Run these commands from the repository root to install Doxygen:

```powershell
$ErrorActionPreference = 'Stop'
$archive = 'third_party/doxygen/doxygen-1.18.0.windows.x64.bin.zip'
Invoke-WebRequest -Uri 'https://www.doxygen.nl/files/doxygen-1.18.0.windows.x64.bin.zip' -OutFile $archive
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne
    'e84f54cfd49ef06b0b16536056dbec0c496323de28abcce53a4269463de35eaf') {
    throw 'Doxygen archive SHA256 mismatch'
}
New-Item -ItemType Directory -Path 'third_party/doxygen/bin' -Force | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $archive).Path)
try {
    foreach ($name in @('doxygen.exe', 'libclang.dll')) {
        [IO.Compression.ZipFileExtensions]::ExtractToFile(
            $zip.GetEntry($name), (Join-Path (Resolve-Path 'third_party/doxygen/bin').Path $name), $true)
    }
}
finally {
    $zip.Dispose()
}
```
