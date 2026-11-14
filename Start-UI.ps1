$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonWindowless = Join-Path $projectDirectory '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonWindowless)) {
    $pythonWindowless = Join-Path $projectDirectory '.runtime\pythonw.exe'
}
if (-not (Test-Path -LiteralPath $pythonWindowless)) {
    throw 'Run Setup.cmd before starting the desktop client.'
}
$desktopScript = Join-Path $projectDirectory 'desktop.py'
Start-Process -FilePath $pythonWindowless -ArgumentList @('"' + $desktopScript + '"') -WorkingDirectory $projectDirectory -WindowStyle Normal
