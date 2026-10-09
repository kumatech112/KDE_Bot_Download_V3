$ErrorActionPreference = "Stop"
$taskProject = Split-Path -Parent $PSScriptRoot
$taskEntry = Join-Path $taskProject "src\main.py"
python $taskEntry
