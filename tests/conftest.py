"""Shared pytest policy for local runs and CI."""

import os
import shutil
from pathlib import Path

import pytest


def release_chroma_systems() -> None:
    """Release Chroma's shared Rust/SQLite handles before filesystem cleanup."""
    import chromadb
    from src.rag import close_chroma_clients

    close_chroma_clients()
    for system in list(chromadb.api.client.SharedSystemClient._identifier_to_system.values()):
        system.stop()
    chromadb.api.client.SharedSystemClient.clear_system_cache()


def cleanup_test_path(path: str | os.PathLike[str]) -> None:
    """Remove a test database and fail loudly if Windows still holds it."""
    target = Path(path)
    if not target.exists():
        return
    release_chroma_systems()
    shutil.rmtree(target)
    if target.exists():
        raise AssertionError(f"test cleanup failed: {target}")


def pytest_collection_modifyitems(config, items):
    """Keep external-service tests opt-in so normal pytest never spends money."""
    enabled = os.getenv("MNEME_RUN_INTEGRATION", "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    if enabled:
        return

    skip_integration = pytest.mark.skip(
        reason="integration tests are opt-in; set MNEME_RUN_INTEGRATION=1",
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
