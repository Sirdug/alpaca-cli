# Requires Windows PowerShell 5.1 or PowerShell 7 on Windows.
[CmdletBinding()]
param(
    [switch]$Mcp,
    [string]$Python,
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'alpaca-cli'),
    [ValidateNotNullOrEmpty()][string]$Ref = 'main',
    [string]$SourceDir,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'
if ($Help) {
    Write-Output @'
Usage: .\install.ps1 [-Mcp] [-Python PATH] [-InstallDir PATH] [-Ref main] [-Help]

Downloads Sirdug/alpaca-cli from GitHub into a private environment on Windows.
No local checkout is needed. Private repositories require authenticated Git.
Requires Python 3.9+ (3.12+ with -Mcp).
Default location: %LOCALAPPDATA%\alpaca-cli
Rerun with the same options to download and install updates.
Use -Ref to select a branch, tag, or commit (default: main).
Developers can use -SourceDir PATH to install a local checkout instead.
No administrator access is needed. Saved credentials are preserved.
PATH is updated for this process only; persistent settings are not changed.
'@
    return
}
if ($env:OS -ne 'Windows_NT') { throw 'Use install.sh on macOS or Linux.' }
if ($SourceDir) {
    $SourceDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($SourceDir)
    if (-not (Test-Path -LiteralPath (Join-Path $SourceDir 'pyproject.toml') -PathType Leaf)) {
        throw 'SourceDir must contain an alpaca-cli checkout with pyproject.toml.'
    }
}
if (-not $Python) {
    foreach ($candidate in @('py.exe', 'python.exe', 'python3.exe')) {
        $found = Get-Command $candidate -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { $Python = $found.Source; break }
    }
}
if (-not $Python) { throw 'Install Python 3.9+ first, or select it with -Python C:\path\to\python.exe.' }
$pythonArgs = @()
if ([IO.Path]::GetFileNameWithoutExtension($Python) -eq 'py') { $pythonArgs = @('-3') }
$minimum = '3.9'
if ($Mcp) { $minimum = '3.12' }
# Passing version components as arguments avoids native quoting differences in PS 5.1.
$versionCheck = 'import sys; sys.exit(sys.version_info[:2] < (int(sys.argv[1]), int(sys.argv[2])))'
$versionParts = $minimum.Split('.')
& $Python @pythonArgs -c $versionCheck @versionParts
if ($LASTEXITCODE -ne 0) { throw "Python $minimum+ is required. Select it with -Python." }

$InstallDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($InstallDir)
$marker = Join-Path $InstallDir '.alpaca-cli-installer'
$venvConfig = Join-Path $InstallDir 'pyvenv.cfg'
if (Test-Path -LiteralPath $InstallDir) {
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf) -or
        -not (Test-Path -LiteralPath $venvConfig -PathType Leaf) -or
        (Get-Content -LiteralPath $marker -Raw).Trim() -ne 'alpaca-cli') {
        throw "Refusing to use an existing unmanaged directory: $InstallDir"
    }
} else {
    & $Python @pythonArgs -m venv $InstallDir
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not create the virtual environment. Check that Python includes venv and retry with a new -InstallDir.'
    }
    Set-Content -LiteralPath $marker -Value 'alpaca-cli' -Encoding ASCII
}
$scriptsDir = Join-Path $InstallDir 'Scripts'
$venvPython = Join-Path $scriptsDir 'python.exe'
& $venvPython -c $versionCheck @versionParts
if ($LASTEXITCODE -ne 0) { throw "Existing environment needs Python $minimum+. Choose a new -InstallDir." }
$packageName = 'alpaca-cli'
if ($Mcp) { $packageName += '[mcp]' }
if ($SourceDir) {
    $package = $SourceDir
    if ($Mcp) { $package += '[mcp]' }
} else {
    $encodedRef = [Uri]::EscapeDataString($Ref)
    if (Get-Command git -CommandType Application -ErrorAction SilentlyContinue) {
        # Let Git use its credential manager; never put tokens in URLs or logs.
        $package = "$packageName @ git+https://github.com/Sirdug/alpaca-cli.git@$encodedRef"
    } else {
        $package = "$packageName @ https://github.com/Sirdug/alpaca-cli/archive/$encodedRef.zip"
    }
    Write-Output "Installing Sirdug/alpaca-cli from GitHub ($Ref)..."
}
# Reinstall even when a branch advances without a package version bump.
& $venvPython -m pip install --upgrade --force-reinstall $package
if ($LASTEXITCODE -ne 0) {
    throw 'Package installation failed. For a private GitHub repository, install Git and sign in with access to Sirdug/alpaca-cli, then retry. Also check that -Ref exists.'
}
if ($Mcp) {
    & $venvPython -c 'from alpaca_cli import mcp_server'
    if ($LASTEXITCODE -ne 0) { throw 'MCP verification failed.' }
}
$alpaca = Join-Path $scriptsDir 'alpaca.exe'
& $alpaca --version
if ($LASTEXITCODE -ne 0) { throw 'CLI verification failed.' }
if ($scriptsDir -notin ($env:Path -split ';')) { $env:Path = "$scriptsDir;$env:Path" }
$quotedScriptsDir = $scriptsDir.Replace("'", "''")
$quotedAlpaca = $alpaca.Replace("'", "''")
Write-Output "`nInstalled in $InstallDir"
Write-Output 'To use alpaca in a new PowerShell session, run:'
Write-Output ('  $env:Path = ''{0};'' + $env:Path' -f $quotedScriptsDir)
Write-Output 'Or run the command directly:'
Write-Output "  & '$quotedAlpaca' setup"
Write-Output "  & '$quotedAlpaca' doctor"
if ($Mcp) { Write-Output "MCP stdio command: $(Join-Path $scriptsDir 'alpaca-mcp.exe')" }
