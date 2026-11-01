param([string]$Configuration='Release')
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$cmake=Get-Command cmake -ErrorAction SilentlyContinue
if($cmake){$exe=$cmake.Source}else{
  $vswhere=Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
  $vs=& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
  $exe=Join-Path $vs 'Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe'
}
& $exe -S $root -B (Join-Path $root 'build') -G 'Visual Studio 17 2022' -A x64
if($LASTEXITCODE){throw 'CMake configure failed'}
& $exe --build (Join-Path $root 'build') --config $Configuration --target scatter_worker -j 6
if($LASTEXITCODE){throw 'C++ build failed'}
