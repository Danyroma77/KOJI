# -*- coding: utf-8 -*-
"""Ricostruisce test_processing_tracker.py in modo compilabile."""
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
TARGET = HERE / "tests" / "test_processing_tracker.py"

HEAD = '''\
# -*- coding: utf-8 -*-
"""
Test per ProcessingTracker e ConfigurationSnapshot (FASE 1B).

Coordina:
- processing_tracker: stages, run, counters, fail/complete
- config_snapshot: snapshot immutabili, hash
- worker: pipeline completa su documento reale (FASE 1B)
- endpoint API: GET /api/documents/{id}/processing
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

import pytest

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

TMP_DATA = Path(tempfile.mkdtemp(prefix="koji_test_"))
os.environ["KOJI_DATA_DIR"] = str(TMP_DATA)

from app.config import settings  # noqa: E402
from app.services.processing_tracker import (  # noqa: E402
    ProcessingTracker,
    StageStatus,
    RunStatus,
    StageType,
    RunType,
)
from app.services.config_snapshot import (  # noqa: E402
    ConfigurationSnapshotService,
    config_snapshot,
)
from app.models import (  # noqa: E402
    ProcessingStageResponse,
    ConfigurationSnapshotResponse,
    ProcessingRunResponse,
    ProcessingDetailResponse,
    DocumentStatus,
)
'''.rstrip() + "\n"

TAIL = '''\
if __name__ == "__main__":
    import sys as _s
    _s.exit(0)
'''
