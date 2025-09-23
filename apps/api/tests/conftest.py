from typing import Any, Dict, List

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _load_test_env() -> None:
    env_path = Path(__file__).parent / "data" / "env_test.json"
    if not env_path.exists():
        return
    import json

    with env_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    for key, value in data.items():
        os.environ.setdefault(key, value)


class _FakeQuery:
    def __init__(self, table: str, rows: List[Dict[str, Any]]):
        self._table = table
        self._rows = rows

    # Upsert chain
    def upsert(self, rows, on_conflict: str = ""):
        if isinstance(rows, list):
            self._rows = rows
        else:
            self._rows = [rows]
        return self

    # Insert chain
    def insert(self, rows):
        if isinstance(rows, list):
            self._rows = rows
        else:
            self._rows = [rows]
        return self

    def select(self, _cols: str = "*"):
        return self

    def execute(self):
        class _Resp:
            def __init__(self, data):
                self.data = data

        return _Resp(self._rows)


class FakeSupabaseClient:
    def __init__(self):
        self.captured: Dict[str, Any] = {}

    def table(self, name: str):
        self.captured["table"] = name
        # Return a new chain object per call to keep state separate
        return _FakeQuery(name, [])


@pytest.fixture()
def test_client():
    # Ensure required env vars exist before importing the app
    _load_test_env()

    # Import after env is set to avoid pydantic settings errors
    from app.main import app  # type: ignore
    from app.supabase_client import (  # type: ignore
        get_current_user_id,
        get_supabase_client,
    )

    # Override dependencies to avoid real Supabase calls
    fake = FakeSupabaseClient()

    def _fake_client():
        return fake

    def _fake_user_id():
        return "00000000-0000-0000-0000-000000000000"

    app.dependency_overrides[get_supabase_client] = _fake_client
    app.dependency_overrides[get_current_user_id] = _fake_user_id

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
