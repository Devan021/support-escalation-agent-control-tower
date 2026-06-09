import asyncio
import json
import sqlite3
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable


EMPTY_STATE: dict[str, Any] = {
    "tickets": {},
    "runs": {},
    "traces": {},
    "approvals": {},
    "outbox": {},
    "drills": {},
    "audit_events": {},
    "metrics": {"node_metrics": {}, "cost_usd": 0.0},
}


class JsonStateStore:
    """SQLite-backed state document store used by the local portfolio runtime."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = asyncio.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate_json_file_if_needed()
        self._init_db()

    async def load(self) -> dict[str, Any]:
        async with self._lock:
            return self._read()

    async def update(self, mutator: Callable[[dict[str, Any]], Any]) -> Any:
        async with self._lock:
            state = self._read()
            result = mutator(state)
            self._write(state)
            return result

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS state_documents "
                "(id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )

    def _read(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM state_documents WHERE id = 'current'").fetchone()
        loaded = json.loads(row[0]) if row else {}
        state = deepcopy(EMPTY_STATE)
        for key, value in loaded.items():
            if isinstance(value, dict) and isinstance(state.get(key), dict):
                state[key].update(value)
            else:
                state[key] = value
        return state

    def _write(self, state: dict[str, Any]) -> None:
        payload = json.dumps(state, indent=2, default=str)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO state_documents (id, payload, updated_at)
                VALUES ('current', ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (payload,),
            )

    def _migrate_json_file_if_needed(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        try:
            text = self.path.read_text(encoding="utf-8").lstrip()
        except UnicodeDecodeError:
            return
        if not text.startswith("{"):
            return
        loaded = json.loads(text)
        self.path.unlink()
        self._init_db()
        self._write(loaded)
