from __future__ import annotations

import pytest

from tristate.config import load_config


@pytest.fixture
def cfg(tmp_path):
    return load_config(
        overrides={
            "project": {"output_dir": str(tmp_path / "data")},
            "hnsw": {"embedder": "hashing"},
            "execution": {"max_concurrency": 1, "max_retries": 2, "backoff_base_s": 0.01},
            "llm": {"cache_enabled": False, "schema_repair_attempts": 1},
            "quality": {"shortcut_audit": False},
        }
    )


@pytest.fixture
def cfg_cached(tmp_path):
    return load_config(
        overrides={
            "project": {"output_dir": str(tmp_path / "data")},
            "hnsw": {"embedder": "hashing"},
            "execution": {"max_concurrency": 1, "max_retries": 2, "backoff_base_s": 0.01},
            "llm": {"cache_enabled": True},
        }
    )
