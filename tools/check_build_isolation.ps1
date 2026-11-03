# Verify that switching native configurations preserves the other build.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$vs = & $vswhere -latest -products '*' -version '[18.0,19.0)' `
    -requires Microsoft.Component.MSBuild Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
    -property installationPath
if ($LASTEXITCODE -ne 0 -or -not $vs) { throw 'Visual Studio 2026 with C++ tools is required.' }
$msbuild = Join-Path $vs 'MSBuild/Current/Bin/MSBuild.exe'

function Build-Configuration([string]$configuration) {
    & $msbuild (Join-Path $repo 'ReCraftLaunch.sln') /t:Build `
        /p:Configuration=$configuration /p:Platform=x64 /nologo /verbosity:quiet
    if ($LASTEXITCODE -ne 0) { throw "Build failed: $configuration" }
}

function Get-NativeHashes([string]$configuration) {
    $directory = Join-Path $repo "build/run/x64/$configuration"
    $exe = if ($configuration -eq 'Debug') { 'reclnch_d.exe' } else { 'reclnch.exe' }
    $hashes = @{}
    foreach ($name in @($exe, 'lib/clnch_native.pyd', 'lib/ckitcore.pyd', 'lib/pyautocore.pyd')) {
        $hashes[$name] = (Get-FileHash -LiteralPath (Join-Path $directory $name) -Algorithm SHA256).Hash
    }
    return $hashes
}

function Assert-Unchanged([hashtable]$before, [hashtable]$after, [string]$configuration) {
    foreach ($name in $before.Keys) {
        if ($before[$name] -ne $after[$name]) { throw "Other build changed: $configuration/$name" }
    }
}

Build-Configuration 'Release'
$release = Get-NativeHashes 'Release'
Build-Configuration 'Debug'
Assert-Unchanged $release (Get-NativeHashes 'Release') 'Release'
$debug = Get-NativeHashes 'Debug'
Build-Configuration 'Release'
Assert-Unchanged $debug (Get-NativeHashes 'Debug') 'Debug'
Assert-Unchanged $release (Get-NativeHashes 'Release') 'Release'
Write-Host 'Build isolation OK: Release -> Debug -> Release; EXE/PYD hashes unchanged.'
