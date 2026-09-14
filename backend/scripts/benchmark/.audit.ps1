Set-Location 'C:/myfile/develop/KOJI'

Write-Host '=== GIT_STATUS ==='
git status --short

Write-Host '=== LOOP_TRACKED_CHECK ==='
$files = @(
  '.dbc.txt',
  '.local_bench.txt',
  '.check_container.ps1',
  '.check_import.py',
  '.probe_setup.ps1',
  '.probe_docker.ps1',
  '.probe_load.py',
  '.probe1.py',
  '.probe2.py'
)

foreach ($f in $files) {
  $tracked = git ls-files $f
  if ($tracked) {
    Write-Host ('{0} => TRACKED: {1}' -f $f, $tracked)
  } else {
    Write-Host ('{0} => UNTRACKED/PATH_NOT_FOUND' -f $f)
  }
}

Write-Host '=== LS_BENCHMARK_DIR ==='
Get-ChildItem -Path 'C:/myfile/develop/KOJI/backend/scripts/benchmark' -Force | 
  Select-Object Name, 
    @{n='SizeKB'; e={[math]::Round($_.Length/1KB,2)}}, 
    LastWriteTime | 
  Format-Table -AutoSize

Write-Host '=== WC_LINES ==='
Get-ChildItem 'C:/myfile/develop/KOJI/backend/scripts/benchmark/*.py' -Force | 
  ForEach-Object {
    $lines = (Get-Content $_.FullName | Measure-Object -Line).Lines
    Write-Host ('{0} lines={1}' -f $_.Name, $lines)
  }
