# Lists Relight processes still running. Run after closing or killing the app;
# expected output is "No Relight processes running."
$left = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='electron.exe' OR Name='Relight.exe'" |
  Where-Object { $_.CommandLine -match 'relight' }

if ($left) {
  $left | Select-Object ProcessId, ParentProcessId, Name, CommandLine | Format-List
  exit 1
}

"No Relight processes running."
