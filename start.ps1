param([switch]$SetupOnly, [switch]$RemoteDependencies)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
. (Join-Path $PSScriptRoot 'bootstrap_uv.ps1')

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
    if (!$basePython) { Write-Host 'No compatible Python found. A private Python runtime will be downloaded into tools\python.' }
    if (Test-Path -LiteralPath $environmentPath) {
        $resolvedEnvironment = [IO.Path]::GetFullPath($environmentPath)
        if ([IO.Path]::GetDirectoryName($resolvedEnvironment) -ne [IO.Path]::GetFullPath($PSScriptRoot)) { throw 'Unexpected Python environment path.' }
        $backupPath = Join-Path $PSScriptRoot ('.venv-replaced-' + [guid]::NewGuid().ToString('N'))
        Move-Item -LiteralPath $resolvedEnvironment -Destination $backupPath
        Write-Host 'The copied or broken Python environment was set aside. Creating one for this PC...'
    } else { Write-Host 'Creating a Python environment for this PC...' }
    if ($basePython) {
        & $basePython @baseArgs -m venv $environmentPath
        if ($LASTEXITCODE -ne 0) {
            $uv = Get-LocalUv
            $baseExecutable = & $basePython @baseArgs -c 'import sys; print(sys.executable)'
            & $uv venv --clear --seed --python $baseExecutable --no-python-downloads $environmentPath
            if ($LASTEXITCODE -ne 0) { throw 'Could not create the environment with the installed Python.' }
        }
    } else {
        $uv = Get-LocalUv
        & $uv venv --python 3.12 --managed-python --seed $environmentPath
        if ($LASTEXITCODE -ne 0) { throw 'Could not download and prepare local Python. Check your internet connection.' }
    }
    if (!(Test-PythonCommand -Executable $environmentPython)) { throw 'Python environment is not runnable.' }
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
$setupArgs = @((Join-Path $PSScriptRoot 'dependencies.py'))
if ($RemoteDependencies) { $setupArgs += '--remote' }
& $environmentPython @setupArgs
if ($LASTEXITCODE -ne 0) { throw 'Dependency setup failed. See the message above.' }
if ($SetupOnly) { Write-Host 'Render desk dependencies are ready.'; exit 0 }
& $environmentPython app.py
exit $LASTEXITCODE
