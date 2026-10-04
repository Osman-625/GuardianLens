"""Serialize existing pipeline starts against attention-agent repairs."""
from __future__ import annotations

import sqlite3


def ensure_attention_idle(con: sqlite3.Connection) -> None:
    """Call inside the pipeline's write transaction before claiming any work."""
    exists = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='attention_agent_runs'"
    ).fetchone()
    if exists and con.execute(
        """SELECT 1 FROM attention_agent_runs WHERE mode='repair'
           AND status IN ('running','paused','stopping') LIMIT 1"""
    ).fetchone():
        raise RuntimeError("finish or stop the attention agent repair run first")
