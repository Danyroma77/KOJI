# backend/scripts/benchmark/benchmark_config.py
from pathlib import Path

MODELS = [
    "sentence-transformers/all-MiniLM-L6-v2",
    "sentence-transformers/longformer-base-4096",
    "nomic-ai/nomic-embed-text-v1.5",
]

CHUNK_SIZES = [500, 1000, 1500]

QUERY_COUNT = 24
TOP_K = 10
RESULTS_DIR = Path("results")
WARMUP_RUNS = 2
MEASURED_RUNS = 5
