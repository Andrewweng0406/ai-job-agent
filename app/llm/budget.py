from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3


class SQLiteDailyBudget:
    """Atomic cross-process budget reservations without storing prompt content."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_daily_cost (
                    usage_date TEXT PRIMARY KEY,
                    spent_usd REAL NOT NULL CHECK (spent_usd >= 0)
                )
                """
            )

    def reserve(self, amount_usd: float, limit_usd: float) -> None:
        if amount_usd < 0 or limit_usd < 0:
            raise ValueError("LLM_BUDGET_AMOUNT_INVALID")
        key = date.today().isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT spent_usd FROM llm_daily_cost WHERE usage_date = ?", (key,)
            ).fetchone()
            spent = float(row[0]) if row else 0.0
            if spent + amount_usd > limit_usd:
                connection.rollback()
                raise RuntimeError("LLM_DAILY_BUDGET_EXCEEDED")
            connection.execute(
                """
                INSERT INTO llm_daily_cost (usage_date, spent_usd) VALUES (?, ?)
                ON CONFLICT(usage_date) DO UPDATE SET spent_usd = excluded.spent_usd
                """,
                (key, spent + amount_usd),
            )
            connection.commit()

    def reconcile(self, reserved_usd: float, actual_usd: float, limit_usd: float) -> None:
        delta = actual_usd - reserved_usd
        if delta == 0:
            return
        key = date.today().isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT spent_usd FROM llm_daily_cost WHERE usage_date = ?", (key,)
            ).fetchone()
            spent = float(row[0]) if row else 0.0
            reconciled = max(0.0, spent + delta)
            connection.execute(
                """
                INSERT INTO llm_daily_cost (usage_date, spent_usd) VALUES (?, ?)
                ON CONFLICT(usage_date) DO UPDATE SET spent_usd = excluded.spent_usd
                """,
                (key, reconciled),
            )
            connection.commit()
        if reconciled > limit_usd:
            # The provider already incurred this cost. Record it before failing closed.
            raise RuntimeError("LLM_DAILY_BUDGET_EXCEEDED_AFTER_RESPONSE")

    def spent_today(self) -> float:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT spent_usd FROM llm_daily_cost WHERE usage_date = ?",
                (date.today().isoformat(),),
            ).fetchone()
        return float(row[0]) if row else 0.0

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)
