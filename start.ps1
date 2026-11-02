param([switch]$SetupOnly)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Test-PythonCommand {
    param([string]$Executable, [string[]]$PrefixArgs = @(), [string]$Code = 'import sys; assert sys.version_info >= (3,10)')
    # Windows PowerShell treats native stderr as an error record; probes must not abort setup.
    $ErrorActionPreference = 'Continue'
    try {
        & $Executable @PrefixArgs -c $Code 2>&1 | Out-Null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

$environmentPath = Join-Path $PSScriptRoot '.venv'
$environmentPython = Join-Path $environmentPath 'Scripts\python.exe'
$workingEnvironment = (Test-Path -LiteralPath $environmentPython) -and (Test-PythonCommand -Executable $environmentPython)
if (!$workingEnvironment) {
    $basePython = $null
    $baseArgs = @()
    $candidates = @()
    if ($env:RENDER_PYTHON) { $candidates += @{ Exe = $env:RENDER_PYTHON; Args = @() } }
    $candidates += @{ Exe = 'py'; Args = @('-3') }, @{ Exe = 'python'; Args = @() }, @{ Exe = 'python3'; Args = @() }
    foreach ($candidate in $candidates) {
        if (!(Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) { continue }
        if (Test-PythonCommand -Executable $candidate.Exe -PrefixArgs $candidate.Args -Code 'import sys, venv; assert sys.version_info >= (3,10); assert sys.prefix == sys.base_prefix') {
            $basePython = $candidate.Exe
            $baseArgs = $candidate.Args
            break
        }
    }
    if (!$basePython) { throw 'Install Python 3.10 or newer on this PC (with pip), then rerun. A copied .venv cannot replace a local Python installation. You can also set RENDER_PYTHON to its python.exe path.' }
    if (Test-Path -LiteralPath $environmentPath) {
        $resolvedEnvironment = [IO.Path]::GetFullPath($environmentPath)
        if ([IO.Path]::GetDirectoryName($resolvedEnvironment) -ne [IO.Path]::GetFullPath($PSScriptRoot)) { throw 'Unexpected Python environment path.' }
        $backupPath = Join-Path $PSScriptRoot ('.venv-replaced-' + [guid]::NewGuid().ToString('N'))
        Move-Item -LiteralPath $resolvedEnvironment -Destination $backupPath
        Write-Host 'The copied or broken Python environment was set aside. Creating one for this PC...'
    } else { Write-Host 'Creating a Python environment for this PC...' }
    & $basePython @baseArgs -m venv $environmentPath
    if ($LASTEXITCODE -ne 0 -or !(Test-PythonCommand -Executable $environmentPython)) { throw 'Could not create the Python environment. Install a standard Python distribution with venv and pip support.' }
}
if (!(Test-PythonCommand -Executable $environmentPython -Code 'import flask, waitress')) {
    Write-Host 'Installing render app dependencies...'
    if (!(Test-PythonCommand -Executable $environmentPython -Code 'import pip')) {
        & $environmentPython -m ensurepip --upgrade
        if ($LASTEXITCODE -ne 0) { throw 'Could not install pip in the project environment. Reinstall Python with pip support.' }
    }
    & $environmentPython -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt') --index-url https://pypi.org/simple
    if ($LASTEXITCODE -ne 0) { throw 'Could not install requirements. Check the internet connection and pip output above.' }
}
if ($SetupOnly) { Write-Host 'Python environment is ready for this PC.'; exit 0 }
& $environmentPython app.py
exit $LASTEXITCODE
