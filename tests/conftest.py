from __future__ import annotations

import pytest

from tristate.config import load_config


@pytest.fixture
def cfg(tmp_path):
    # fast single-call base artifact so the pipeline tests stay quick
    return load_config(
        overrides={
            "project": {"output_dir": str(tmp_path / "data")},
            "hnsw": {
                "embedder": "hashing",
                "near_duplicate_cosine": 1.0,
                "near_duplicate_jaccard": 1.0,
            },
            "execution": {"max_concurrency": 1, "max_retries": 2, "backoff_base_s": 0.01},
            "llm": {"cache_enabled": False, "schema_repair_attempts": 1},
            "quality": {"shortcut_audit": False},
            "blueprint": {"candidates_per_topic": 1},
            "passage": {
                "target_tokens_min": 80,
                "target_tokens_max": 120,
                "single_call_below_tokens": 200,
                "sections_min": 2,
                "sections_max": 3,
                "section_tokens_min": 80,
                "section_tokens_max": 120,
                "max_sections": 4,
            },
            "extraction": {"window_tokens": 0},
            "claims": {"min_distinct_sections": 1},
        }
    )


@pytest.fixture
def cfg_long(tmp_path):
    # exercises the sectioned long-form path with deterministic mock workers
    return load_config(
        overrides={
            "project": {"output_dir": str(tmp_path / "data-long")},
            "hnsw": {
                "embedder": "hashing",
                "near_duplicate_cosine": 1.0,
                "near_duplicate_jaccard": 1.0,
            },
            "execution": {
                "max_concurrency": 1,
                "max_retries": 2,
                "backoff_base_s": 0.01,
                "max_calls_per_family": 80,
            },
            "llm": {"cache_enabled": False, "schema_repair_attempts": 1},
            "quality": {"shortcut_audit": False},
            "passage": {
                "target_tokens_min": 800,
                "target_tokens_max": 1200,
                "single_call_below_tokens": 100,
                "sections_min": 3,
                "sections_max": 4,
                "section_tokens_min": 250,
                "section_tokens_max": 400,
                "max_sections": 6,
                "max_cross_section_overlap": 1.0,
                "min_document_ratio": 0.2,
                "max_document_ratio": 5.0,
            },
            "extraction": {"window_tokens": 0},
            "claims": {"min_distinct_sections": 2},
            "variants": {"long_document_tokens": 400},
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
