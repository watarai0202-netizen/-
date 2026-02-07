from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

# 非スクレイピングのJSONインデックス（やのしん TDnet WEB-API）
# 必要なら環境変数で差し替え可能にする
TDNET_BASE = "https://webapi.yanoshin.jp/webapi/tdnet/list"


def _parse_dt_maybe(value: str | None) -> datetime | None:
    if not value:
        return None
    s = value.strip()
    # よくあるISO形式のZ
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _normalize_item(raw: dict[str, Any]) -> dict[str, Any]:
    """
    APIレスポンスの形が多少揺れても壊れないように、保守的に正規化する。
    """
    td = raw.get("TDnet") if isinstance(raw.get("TDnet"), dict) else raw

    title = td.get("title") or td.get("Title") or ""
    code = td.get("code") or td.get("Code") or ""

    # URLキーが揺れた場合に備える
    doc_url = (
        td.get("document_url")
        or td.get("documentUrl")
        or td.get("doc_url")
        or td.get("url")
        or ""
    )

    published_raw = td.get("published_at") or td.get("pubdate") or td.get("date") or ""
    published_at = _parse_dt_maybe(published_raw)

    return {
        "title": str(title),
        "code": str(code) if code is not None else "",
        "doc_url": str(doc_url),
        "published_at": published_at,
        "raw": td,
    }


def fetch_tdnet_items(code: str | None, limit: int = 200) -> list[dict[str, Any]]:
    """
    code があれば銘柄別、なければrecent。
    """
    if code and code.isdigit() and len(code) == 4:
        url = f"{TDNET_BASE}/{code}.json?limit={limit}"
    else:
        url = f"{TDNET_BASE}/recent.json?limit={limit}"

    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    data = r.json()

    items = data.get("items")
    if not isinstance(items, list):
        # 万一形が違ったら空で返す（壊れにくさ優先）
        return []

    out: list[dict[str, Any]] = []
    for raw in items:
        if isinstance(raw, dict):
            out.append(_normalize_item(raw))
    return out
