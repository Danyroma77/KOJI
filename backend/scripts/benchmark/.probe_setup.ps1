# Verifica setup benchmark nel container e controllo import
$dc = 'docker'
$name = 'koji-api'

function ProbeContainer() {
    Write-Output "CHECK_CONTAINER:$name"
    $ps = & $dc ps --filter "name=$name" --format "{{.Names}}" 2>&1
    if ($LASTEXITCODE -ne 0) { Write-Output "CONTAINER_STATUS:ERROR:$ps"; return }
    if ($ps -notmatch $name) { Write-Output "CONTAINER_STATUS:NOT_FOUND"; return }
    Write-Output "CONTAINER_STATUS:RUNNING"

    Write-Output "CHECK_BENCHMARK_PATH:/app/scripts/benchmark"
    $ls = & $dc exec $name /bin/sh -c 'ls -1 /app/scripts/benchmark/ 2>/dev/null' 2>&1
    if ($LASTEXITCODE -ne 0 -or -not $ls) { Write-Output "CHECK_BENCHMARK_PATH:MISSING"; return }
    Write-Output "CHECK_BENCHMARK_PATH:PRESENT"
    Write-Output "FILES:"
    $ls -split "`n" | ForEach-Object { Write-Output "  $_" }
}

function CopyCode() {
    Write-Output "COPY_CODE:FROM_HOST_TO_CONTAINER_START"
    $src = 'backend/scripts/benchmark'
    $dst = '/app/scripts/benchmark'
    $exists = & $dc exec $name /bin/sh -c "[ -d '$dst' ] && echo EXISTS || echo MISSING" 2>&1
    Write-Output "DEST_EXISTS:$exists"

    if ($exists -notmatch 'EXISTS') {
        $mkdir = & $dc exec $name /bin/sh -c 'mkdir -p /app/scripts/benchmark' 2>&1
        Write-Output "MKDIR_RESULT:$mkdir"
    }

    $copy = & $dc cp $src "${name}:${dst}" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Output "COPY_RESULT:FAILED:$copy"
        return
    }
    Write-Output "COPY_RESULT:OK"
    $verify = & $dc exec $name /bin/sh -c "ls -1 /app/scripts/benchmark" 2>&1
    Write-Output "VERIFY_LISTING:$verify"
}

function CheckImport() {
    Write-Output "CHECK_IMPORTS:START"
    $cmd = 'from pathlib import Path; import sys; from importlib import import_module; mod=import_module("scripts.benchmark.embedding_benchmark"); print("IMPORT_OK:", getattr(mod, "__file__", None))'
    $out = & $dc exec $name python -c $cmd 2>&1
    Write-Output "IMPORT_OUTPUT:$out"
    if ($LASTEXITCODE -ne 0) { Write-Output "IMPORT_RESULT:FAILED"; return }
    Write-Output "IMPORT_RESULT:OK"
}

ProbeContainer
CopyCode
CheckImport
