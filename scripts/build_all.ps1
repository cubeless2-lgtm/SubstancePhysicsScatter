# Build the legacy, review and live workers from a clean Windows checkout.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$cmake = Get-Command cmake -ErrorAction SilentlyContinue
if ($cmake) { $exe = $cmake.Source } else {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
    if (-not (Test-Path $vswhere)) { throw 'Install Visual Studio 2022 Desktop development with C++ and CMake.' }
    $vs = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if (-not $vs) { throw 'Visual Studio C++ tools not found.' }
    $exe = Join-Path $vs 'Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe'
}
function Configure-Build([string]$source, [string]$directory, [string[]]$options) {
    & $exe -S $source -B $directory -G 'Visual Studio 17 2022' -A x64 @options
    if ($LASTEXITCODE -ne 0) { throw "CMake configure failed: $directory" }
    & $exe --build $directory --config Release -j 6
    if ($LASTEXITCODE -ne 0) { throw "CMake build failed: $directory" }
}
Configure-Build $root (Join-Path $root 'build') @()
Configure-Build $root (Join-Path $root 'build-review') @('-DSCATTER_REVIEW_BUILD=ON')
Configure-Build $root (Join-Path $root 'build-review-pbr') @('-DSCATTER_REVIEW_BUILD=ON', '-DSCATTER_REVIEW_PBR_BUILD=ON')
Configure-Build (Join-Path $root 'worker/motion') (Join-Path $root 'build-review-live-ready1') @('-DSCATTER_LIVE_BUILD=ON')
