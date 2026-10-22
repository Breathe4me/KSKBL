param([Parameter(Mandatory=$true)][string]$Python, [Parameter(Mandatory=$true)][string]$Node, [Parameter(Mandatory=$true)][string]$PlaywrightModule, [string]$DependencyDir='')
$ErrorActionPreference='Stop'
$project=Split-Path $PSScriptRoot -Parent
$previousPath=$env:PYTHONPATH
$previousBytecode=$env:PYTHONDONTWRITEBYTECODE
$previousPython=$env:CDA_TEST_PYTHON
$previousPlaywright=$env:CDA_PLAYWRIGHT
Push-Location $project
try {
    $env:PYTHONDONTWRITEBYTECODE='1'
    $env:PYTHONPATH="$project\src;$project\scripts;$project\.ui-deps;$DependencyDir"
    $env:CDA_TEST_PYTHON=$Python
    $env:CDA_PLAYWRIGHT=$PlaywrightModule
    & $Python -B -m ruff check src tests scripts
    if ($LASTEXITCODE -ne 0) { throw 'Code checks failed' }
    # These two files create real Tk windows. Preserve them but defer execution to an authorized VM session.
    & $Python -B -m pytest -q -p code_only_guard --ignore=tests/test_gui.py --ignore=tests/test_v12_desktop.py -o cache_dir=reports/.pytest-codeonly --junitxml=reports/codeonly-regression.xml
    if ($LASTEXITCODE -ne 0) { throw 'Code-only regressions failed' }
    & $Node --check frontend/app.js
    if ($LASTEXITCODE -ne 0) { throw 'JavaScript syntax failed' }
    & $Python -B -c "from pathlib import Path;from canvas_agent.web_shell import html_document;Path('reports/headless-doc.html').write_text(html_document(),encoding='utf-8')"
    if ($LASTEXITCODE -ne 0) { throw 'Offline HTML assembly failed' }
    & $Node scripts/test_frontend.cjs
    if ($LASTEXITCODE -ne 0) { throw 'Headless DOM tests failed' }
} finally {
    $env:PYTHONPATH=$previousPath
    $env:PYTHONDONTWRITEBYTECODE=$previousBytecode
    $env:CDA_TEST_PYTHON=$previousPython
    $env:CDA_PLAYWRIGHT=$previousPlaywright
    Pop-Location
}
