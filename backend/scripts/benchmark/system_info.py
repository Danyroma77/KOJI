# backend/scripts/benchmark/system_info.py
import platform
import psutil
import torch
import transformers
import sentence_transformers
import tokenizers
from datetime import datetime
from pathlib import Path
import subprocess
import json

def get_environment_snapshot():
    snapshot = {
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip(),
        "timestamp": datetime.utcnow().isoformat(),
        "python_version": platform.python_version(),
        "torch_version": torch.__version__,
        "transformers_version": transformers.__version__,
        "sentence_transformers_version": sentence_transformers.__version__,
        "tokenizers_version": tokenizers.__version__,
        "cpu": platform.processor() or "unknown",
        "ram_mb": psutil.virtual_memory().total / (1024 * 1024),
        "gpu_available": torch.cuda.is_available(),
        "os": platform.system(),
        "docker": True,
    }
    return snapshot

def save_environment_snapshot(snapshot, results_dir):
    snapshot_path = results_dir / "environment_snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot, indent=2))
