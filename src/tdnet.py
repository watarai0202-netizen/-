from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None  # type: ignore

# 非スクレイピングのJSONインデックス（やのしん TDnet WEB-API）
TDNET_BASE = os.getenv("TDNET_BASE", "https://webapi.yanoshin.jp/webapi/tdnet/list")

_JST = timezone(timedelta(hours=9))


def _parse_dt_maybe(value: str | None) -> datetime | None:
    """
    - ISO: 2026-02-06T20:00:00Z / +09:00
    - "YYYY-mm-dd HH:MM:SS"（tz無し）→ JST想定
    返り値はUTC tz-aware datetime
    """
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None

    s = s.replace("Z", "+00:00")

    try:
        dt = datetime.fromisoformat(s)  # "YYYY-mm-dd HH:MM:SS" も通る
        if dt.tzinfo is None:
            # tz無しはJST想定（環境差でズレないよう固定で+09:00にする）
            if ZoneInfo is not None:
                dt = dt.replace(tzinfo=ZoneInfo("Asia/Tokyo"))
            else:
                dt = dt.replace(tzinfo=_JST)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _pick_tdnet_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """
    APIレスポンスのキー揺れ（TDnet / Tdnet / tdnet）に対応。
    """
    for k in ("TDnet", "Tdnet", "tdnet"):
        v = raw.get(k)
        if isinstance(v, dict):
            return v
    return raw


def _code4_from_company_code(company_code: str) -> str:
    """
    app.pyの _code4() と揃える：
    - 5桁末尾0: 45230 -> 4523
    - 4桁: 7203 -> 7203
    - その他: 先頭4桁が数字なら採用
    """
    s = (company_code or "").strip()
    if not s.isdigit():
        return ""
    if len(s) == 5 and s.endswith("0"):
        return s[:-1]
    if len(s) >= 4:
        return s[:4]
    return ""


def _normalize_item(raw: dict[str, Any]) -> dict[str, Any]:
    td = _pick_tdnet_dict(raw)

    title = td.get("title") or td.get("Title") or ""
    company_code = (
        td.get("company_code")
        or td.get("CompanyCode")
        or td.get("code")
        or td.get("Code")
        or ""
    )
    company_name = td.get("company_name") or td.get("CompanyName") or ""

    # URLキーが揺れた場合に備える
    doc_url = (
        td.get("document_url")
        or td.get("documentUrl")
        or td.get("doc_url")
        or td.get("url")
        or ""
    )

    published_raw = td.get("published_at") or td.get("pubdate") or td.get("date") or ""
    published_at = _parse_dt_maybe(str(published_raw) if published_raw is not None else None)

    company_code_s = str(company_code) if company_code is not None else ""
    code4 = _code4_from_company_code(company_code_s)

    return {
        "title": str(title).strip(),
        "company_code": company_code_s.strip(),
        "code4": code4,
        "company_name": str(company_name).strip(),
        "doc_url": str(doc_url).strip(),
        "published_at": published_at,
        "raw": td,  # ここは app.py が救済に使うので維持
    }


def _get_json(url: str, timeout: float = 20.0, retries: int = 2) -> dict[str, Any]:
    """
    軽いリトライ付きGET。
    """
    last_err = None
    for i in range(retries + 1):
        try:
            r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, dict) else {"items": []}
        except Exception as e:
            last_err = e
            if i < retries:
                time.sleep(0.8 * (i + 1))
                continue
            break
    # 壊れにくさ優先：例外を投げず空扱い
    return {"items": []}


def fetch_tdnet_items(code: str | None, limit: int = 200) -> list[dict[str, Any]]:
    """
    code があれば銘柄別、なければrecent。
    """
    if code and code.isdigit() and len(code) == 4:
        url = f"{TDNET_BASE}/{code}.json?limit={limit}"
    else:
        url = f"{TDNET_BASE}/recent.json?limit={limit}"

    data = _get_json(url, timeout=20.0, retries=2)
    items = data.get("items")
    if not isinstance(items, list):
        return []

    out: list[dict[str, Any]] = []
    for raw in items:
        if isinstance(raw, dict):
            out.append(_normalize_item(raw))
    return out
