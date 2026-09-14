# probe esplicito stato e mapping container koji-api
$dc = 'docker'
$name = 'koji-api'

Write-Output "CHECK_CONTAINER:$name"
try {
    $ps = & $dc ps --filter "name=$name" --format "{{.Names}}" 2>&1
    if ($LASTEXITCODE -ne 0) { throw "docker ps failed: $ps" }
    if ($ps -notmatch $name) {
        Write-Output "CONTAINER_STATUS: NOT_FOUND"
        exit
    }
    Write-Output "CONTAINER_STATUS: RUNNING"
} catch {
    Write-Output "CONTAINER_STATUS: ERROR:$($_)"
    exit
}

Write-Output "CHECK_BENCHMARK_FILE:/app/scripts/benchmark/embedding_benchmark.py"
try {
    $ls = & $dc exec $name /bin/sh -c 'test -f /app/scripts/benchmark/embedding_benchmark.py && echo OK || echo MISSING' 2>&1
    Write-Output "BENCHMARK_FILE_STATUS:$ls"
} catch {
    Write-Output "BENCHMARK_FILE_STATUS:ERROR:$($_)"
    exit
}

Write-Output "CHECK_DIR_LISTING:/app/scripts/benchmark"
try {
    $l = & $dc exec $name /bin/sh -c 'ls -1 /app/scripts/benchmark/' 2>&1
    Write-Output "DIR_LISTING:"
    $l -split "`n" | ForEach-Object { Write-Output "  $_" }
} catch {
    Write-Output "DIR_LISTING:ERROR:$($_)"
    exit
}

Write-Output "CHECK_PYTHON_IN_CONTAINER"
try {
    $v = & $dc exec $name /usr/bin/python3 -c "import sys; print('PY', sys.version.split()[0])" 2>&1
    Write-Output "PYTHON_VERSION:$v"
} catch {
    Write-Output "PYTHON_VERSION:ERROR:$($_)"
    exit
}
