param([ValidateRange(1, 65535)][int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$candidates = @('.venv\Scripts\python.exe', '.venv-win\Scripts\python.exe')
$selectedPython = $null
foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate) {
        try {
            & $candidate -c 'import fastapi, pydantic, uvicorn' 2>$null
            if ($LASTEXITCODE -eq 0) { $selectedPython = $candidate; break }
        } catch { }
    }
}
if (-not $selectedPython) {
    Write-Host 'No ready Python environment. Use standard Windows Python 3.11+:'
    Write-Host 'python -m venv .venv'
    Write-Host '.\.venv\Scripts\python.exe -m pip install -c requirements-dev.lock.txt -e ".[dev]"'
    Write-Host 'Wait for Successfully installed, then run .\start.ps1 again.'
    exit 1
}
Write-Host "Using $selectedPython"
if (-not (Test-Path -LiteralPath 'frontend\dist\index.html')) {
    if (-not (Test-Path -LiteralPath 'frontend\node_modules') -or -not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
        Write-Host 'Frontend is not built. Run .\setup.ps1 first.'
        exit 1
    }
    Push-Location frontend
    try {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
    } finally { Pop-Location }
}
& $selectedPython -m backend.run --port $Port
exit $LASTEXITCODE
