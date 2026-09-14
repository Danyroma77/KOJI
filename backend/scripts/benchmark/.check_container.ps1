$dc='docker'
$name='koji-api'

Write-Output "CHECK_CONTAINER:$name"

function Run($cmd) {
    Write-Output "RUN:$cmd"
    & $dc exec ${name} /bin/sh -c $cmd 2>&1
    Write-Output "---"
}

Run "ls -la /app/scripts/benchmark"
Run "ls -la /app/scripts/benchmark/benchmark 2>&1 || echo NO_SUB_BENCH"
Run "test -f /app/scripts/benchmark/embedding_benchmark.py && echo FB_EXISTS || echo FB_MISSING"
Run "test -f /app/scripts/__init__.py && echo INIT_EXISTS || echo INIT_MISSING"
Run "head -10 /app/scripts/benchmark/.check_import.py 2>&1 || echo NO_CHECK_IMPORT"
