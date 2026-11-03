# Shared Windows VERSIONINFO check for packaging and archive creation.
param(
    [Parameter(Mandatory)]
    [string]$Executable,
    [Parameter(Mandatory)]
    [string]$ExpectedVersion
)

$ErrorActionPreference = 'Stop'
$version = [Diagnostics.FileVersionInfo]::GetVersionInfo([IO.Path]::GetFullPath($Executable))
$parts = @($ExpectedVersion.Split('.') | ForEach-Object { [int]$_ }) + @(0)
if ($version.ProductName -ne 'ReCraftLaunch' -or $version.ProductVersion -ne $ExpectedVersion -or
        $version.FileVersion -ne $ExpectedVersion -or $version.OriginalFilename -ne 'reclnch.exe' -or
        $version.IsDebug -or
        $version.FileMajorPart -ne $parts[0] -or $version.FileMinorPart -ne $parts[1] -or
        $version.FileBuildPart -ne $parts[2] -or $version.FilePrivatePart -ne $parts[3] -or
        $version.ProductMajorPart -ne $parts[0] -or $version.ProductMinorPart -ne $parts[1] -or
        $version.ProductBuildPart -ne $parts[2] -or $version.ProductPrivatePart -ne $parts[3]) {
    throw "Release executable version information differs from $ExpectedVersion."
}
