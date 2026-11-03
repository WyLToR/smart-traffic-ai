$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$pythonPath = Join-Path $PWD ".venv/Scripts/python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Hiányzik a virtuális környezet. Kövesd a README telepítési útmutatóját."
}
& $pythonPath -m pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonPath -m ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonPath -m compileall -q src
exit $LASTEXITCODE
