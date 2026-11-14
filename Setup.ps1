$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectDirectory
$venvPython = Join-Path $projectDirectory '.venv\Scripts\python.exe'
$embeddedPython = Join-Path $projectDirectory '.runtime\python.exe'
if (Test-Path -LiteralPath $embeddedPython) {
    $installPython = $embeddedPython
} else {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            & py -3 -m venv (Join-Path $projectDirectory '.venv')
        } elseif (Get-Command python -ErrorAction SilentlyContinue) {
            & python -m venv (Join-Path $projectDirectory '.venv')
        } else {
            throw 'Install Python 3.12 for Windows from python.org, then run Setup.cmd again.'
        }
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPython)) {
            throw 'Could not create a Python virtual environment. Install Python 3.12 from python.org.'
        }
    }
    $installPython = $venvPython
}
& $installPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Could not update pip.' }
& $installPython -m pip install '.[desktop]'
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
$stateDirectory = Join-Path $projectDirectory '.deployment'
New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
Write-Output 'Installed. Open UI.cmd, configure your account, then connect.'
