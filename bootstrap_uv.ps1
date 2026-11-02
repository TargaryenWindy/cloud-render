function Get-LocalUv {
    $uvPath = Join-Path $PSScriptRoot 'tools\uv\uv.exe'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $PSScriptRoot 'tools\python'
    $env:UV_CACHE_DIR = Join-Path $PSScriptRoot 'tools\uv-cache'
    $env:UV_PYTHON_INSTALL_BIN = '0'
    $env:UV_NO_MODIFY_PATH = '1'
    if (!(Test-Path -LiteralPath $uvPath)) {
        $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'aarch64' } else { 'x86_64' }
        $package = "uv-$arch-pc-windows-msvc.zip"
        $tempFolder = Join-Path $PSScriptRoot ('tools\uv-setup-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force $tempFolder | Out-Null
        $archive = Join-Path $tempFolder $package
        Write-Host 'Preparing a local Python setup helper (uv)...'
        Invoke-WebRequest "https://github.com/astral-sh/uv/releases/latest/download/$package" -OutFile $archive
        Expand-Archive -LiteralPath $archive -DestinationPath $tempFolder
        $binary = Get-ChildItem -LiteralPath $tempFolder -Recurse -Filter uv.exe | Select-Object -First 1
        if (!$binary) { throw 'uv download did not contain uv.exe.' }
        New-Item -ItemType Directory -Force (Split-Path $uvPath) | Out-Null
        Move-Item -LiteralPath $binary.FullName -Destination $uvPath
        $resolvedTemp = [IO.Path]::GetFullPath($tempFolder)
        $toolsRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'tools')) + [IO.Path]::DirectorySeparatorChar
        if (!$resolvedTemp.StartsWith($toolsRoot)) { throw 'Unexpected setup temporary path.' }
        Remove-Item -LiteralPath $resolvedTemp -Recurse -Force
    }
    return $uvPath
}
