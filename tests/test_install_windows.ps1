param(
    [Parameter(Mandatory = $true)][string]$Python,
    [switch]$Mcp,
    [switch]$FromGitHub
)
$ErrorActionPreference = 'Stop'
$installer = Join-Path (Split-Path $PSScriptRoot -Parent) 'install.ps1'
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('alpaca-install-test-' + [guid]::NewGuid())
$installDir = Join-Path $testRoot 'environment with spaces'
$originalPath = $env:Path
$sourceOptions = @{}
if (-not $FromGitHub) { $sourceOptions.SourceDir = Split-Path $PSScriptRoot -Parent }
try {
    if ($FromGitHub) {
        New-Item -ItemType Directory -Path $testRoot | Out-Null
        $standalone = Join-Path $testRoot 'install.ps1'
        Copy-Item -LiteralPath $installer -Destination $standalone
        $installer = $standalone
    }
    & $installer -Python $Python -InstallDir $installDir -Mcp:$Mcp @sourceOptions
    & (Join-Path $installDir 'Scripts\alpaca.exe') --help
    if ($LASTEXITCODE -ne 0) { throw 'Installed command failed.' }
    & $installer -Python $Python -InstallDir $installDir -Mcp:$Mcp @sourceOptions
    $unmanaged = Join-Path $testRoot 'unmanaged'
    New-Item -ItemType Directory -Path $unmanaged | Out-Null
    Set-Content -LiteralPath (Join-Path $unmanaged 'keep.txt') -Value 'preserve me'
    $rejected = $false
    try { & $installer -Python $Python -InstallDir $unmanaged }
    catch {
        if ($_.Exception.Message -notlike '*unmanaged directory*') { throw }
        $rejected = $true
    }
    if (-not $rejected) { throw 'Unmanaged directory was not rejected.' }
    if ((Get-Content -LiteralPath (Join-Path $unmanaged 'keep.txt') -Raw).Trim() -ne 'preserve me') {
        throw 'Existing file was modified.'
    }
    Write-Output 'Windows installer checks passed.'
} finally {
    $env:Path = $originalPath
    # Only remove this test's unique directory, after verifying its parent.
    $resolved = [IO.Path]::GetFullPath($testRoot)
    $tempParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
    if ((Split-Path $resolved -Parent) -eq $tempParent -and
        (Split-Path $resolved -Leaf) -like 'alpaca-install-test-*' -and
        (Test-Path -LiteralPath $resolved)) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
