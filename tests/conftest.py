"""Pytest fixtures for tests."""

import tempfile
from pathlib import Path

import pytest

from src.api.sim import clear_exposures
from src.core.db import init_db


@pytest.fixture
def db_conn():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    conn = init_db(db_path)
    clear_exposures()

    yield conn

    conn.close()
    db_path.unlink(missing_ok=True)
    # Also remove WAL and SHM files
    Path(str(db_path) + "-wal").unlink(missing_ok=True)
    Path(str(db_path) + "-shm").unlink(missing_ok=True)
