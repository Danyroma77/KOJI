#!/usr/bin/env python3
import sys
from pathlib import Path

app = Path("/app")
scripts = app / "scripts"
benchmark_in_container = scripts / "benchmark"

print("APPSCRIPTS_EXISTS:", scripts.exists())
print("BENCHMARK_IN_CONTAINER_EXISTS:", benchmark_in_container.exists())
print("BENCHMARK_FILES:", sorted(p.name for p in benchmark_in_container.iterdir()) if benchmark_in_container.exists() else "MISSING")
scripts_init = scripts / "__init__.py"
print("SCRIPTS_INIT_EXISTS:", scripts_init.exists())

sys.path.insert(0, str(app))
try:
    import scripts.benchmark.embedding_benchmark as bm
    print("IMPORT_OK:", getattr(bm, "__file__", None) is not None)
except Exception as e:
    print("IMPORT_ERROR:", type(e).__name__, str(e)[:300])
    sys.exit(1)
