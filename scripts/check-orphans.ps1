# Lists Relight processes still running. Run after closing or killing the app;
# expected output is "No Relight processes running."
# Matches the backend by its module name and Electron by this repo's folder.
$repo = [regex]::Escape((Split-Path $PSScriptRoot -Parent))
$left = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='electron.exe' OR Name='Relight.exe'" |
  Where-Object { $_.CommandLine -match "relight_backend|$repo" }

if ($left) {
  $left | Select-Object ProcessId, ParentProcessId, Name, CommandLine | Format-List
  exit 1
}

"No Relight processes running."
