param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$runtimePython = $null
foreach ($candidate in @('.venv\Scripts\python.exe', '.venv-win\Scripts\python.exe')) {
    if (Test-Path -LiteralPath $candidate) {
        try {
            & $candidate -c 'import sys; assert sys.platform == "win32"' 2>$null
            if ($LASTEXITCODE -eq 0) { $runtimePython = $candidate; break }
        } catch { }
    }
}
if (-not $runtimePython) {
    & $Python -c 'import sys; assert sys.platform == "win32" and sys.version_info >= (3, 11), "Use Windows CPython 3.11+"'
    if ($LASTEXITCODE -ne 0) { throw 'Use standard Windows CPython 3.11+, or pass -Python with its full path.' }
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create .venv' }
    $runtimePython = '.venv\Scripts\python.exe'
}
& $runtimePython -m pip install -c requirements-dev.lock.txt -e '.[dev]'
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed or was cancelled. Rerun setup.ps1.' }
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Install Node.js 22+ and rerun setup.ps1.' }
Push-Location frontend
try {
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
} finally { Pop-Location }
Write-Host 'Ready. Start with .\start.ps1 and open http://127.0.0.1:8000/'
