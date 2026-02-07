from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone


def db_path_default() -> str:
    # Streamlit Cloudでも書き込み可能な場所をデフォルトに
    # ローカルは app.db に変えてもOK（Secretsで指定可）
    return "/tmp/app.db"


def init_db(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True) if "/" in db_path else None
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS analyses (
      doc_url TEXT PRIMARY KEY,
      code TEXT,
      title TEXT,
      published_at TEXT,
      payload_json TEXT,
      created_at TEXT
    )
    """)
    con.commit()
    con.close()


def get_cached_analysis(db_path: str, doc_url: str) -> dict | None:
    if not doc_url:
        return None
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT payload_json FROM analyses WHERE doc_url=?", (doc_url,))
    row = cur.fetchone()
    con.close()
    if not row:
        return None
    try:
        return json.loads(row[0])
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
    if published_at is not None:
        try:
            published_str = published_at.astimezone(timezone.utc).isoformat()
        except Exception:
            published_str = str(published_at)

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("""
      INSERT OR REPLACE INTO analyses(doc_url, code, title, published_at, payload_json, created_at)
      VALUES(?,?,?,?,?,?)
    """, (
        doc_url,
        code,
        title,
        published_str,
        json.dumps(payload, ensure_ascii=False),
        datetime.now(timezone.utc).isoformat(),
    ))
    con.commit()
    con.close()
