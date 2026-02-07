from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


def db_path_default() -> str:
    return "/tmp/app.db"


def _connect(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path, timeout=30)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con


_JST = timezone(timedelta(hours=9))


def init_db(db_path: str) -> None:
    if "/" in db_path:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    con = _connect(db_path)
    cur = con.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS analyses (
          doc_url TEXT PRIMARY KEY,
          code TEXT,
          title TEXT,
          published_at TEXT,
          payload_json TEXT,
          created_at TEXT
        )
        """
    )

    # 追加カラム（既存互換）
    _ensure_column(cur, "analyses", "model", "TEXT")
    _ensure_column(cur, "analyses", "tokens", "INTEGER")
    _ensure_column(cur, "analyses", "schema_version", "INTEGER")

    # ★グルーピング用（新規）
    _ensure_column(cur, "analyses", "code4", "TEXT")
    _ensure_column(cur, "analyses", "published_date_jst", "TEXT")  # YYYY-MM-DD
    _ensure_column(cur, "analyses", "doc_type", "TEXT")            # kessan / briefing / other

    # ★検索を速くするINDEX（存在しなければ作成）
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_analyses_code4_date ON analyses(code4, published_date_jst)"
    )

    con.commit()
    con.close()


def _ensure_column(cur: sqlite3.Cursor, table: str, col: str, coltype: str) -> None:
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    if col in cols:
        return
    cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")


def get_cached_analysis(db_path: str, doc_url: str) -> dict | None:
    if not doc_url:
        return None

    con = _connect(db_path)
    cur = con.cursor()

    try:
        cur.execute(
            """
            SELECT payload_json, model, tokens, schema_version, code4, published_date_jst, doc_type
            FROM analyses WHERE doc_url=?
            """,
            (doc_url,),
        )
        row = cur.fetchone()
        con.close()
        if not row:
            return None

        payload_raw = row[0]
        model, tokens, schema_version = row[1], row[2], row[3]
        code4, date_jst, doc_type = row[4], row[5], row[6]
    except Exception:
        cur.execute("SELECT payload_json FROM analyses WHERE doc_url=?", (doc_url,))
        row = cur.fetchone()
        con.close()
        if not row:
            return None
        payload_raw = row[0]
        model = tokens = schema_version = code4 = date_jst = doc_type = None

    try:
        payload = json.loads(payload_raw)
        if isinstance(payload, dict):
            if model and "model" not in payload:
                payload["model"] = model
            if tokens is not None and "tokens" not in payload:
                payload["tokens"] = tokens
            if schema_version is not None and "schema_version" not in payload:
                payload["schema_version"] = schema_version
            # ★DB側の束ねキーも補完
            if code4 and "code4" not in payload:
                payload["code4"] = code4
            if date_jst and "published_date_jst" not in payload:
                payload["published_date_jst"] = date_jst
            if doc_type and "doc_type" not in payload:
                payload["doc_type"] = doc_type
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def save_analysis(
    db_path: str,
    doc_url: str,
    code: str,
    title: str,
    published_at,
    payload: dict,
) -> None:
    if not doc_url:
        return

    published_str = ""
    date_jst = ""
    if published_at is not None:
        try:
            published_str = published_at.astimezone(timezone.utc).isoformat()
            date_jst = published_at.astimezone(_JST).strftime("%Y-%m-%d")
        except Exception:
            published_str = str(published_at)
            date_jst = ""
    # code4 は code を優先（app.pyではcode=4桁に寄せてる）
    code4 = (code or "").strip()[:4] if (code or "").strip() else ""

    model = _infer_model(payload)
    tokens = _infer_tokens(payload)
    schema_version = _infer_schema_version(payload)
    doc_type = _infer_doc_type(title, payload)

    con = _connect(db_path)
    cur = con.cursor()

    try:
        cur.execute(
            """
            INSERT OR REPLACE INTO analyses
              (doc_url, code, title, published_at, payload_json, created_at,
               model, tokens, schema_version,
               code4, published_date_jst, doc_type)
            VALUES (?,?,
