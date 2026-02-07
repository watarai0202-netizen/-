from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None  # type: ignore

# 非スクレイピングのJSONインデックス（やのしん TDnet WEB-API）
TDNET_BASE = os.getenv("TDNET_BASE", "https://webapi.yanoshin.jp/webapi/tdnet/list")


def _parse_dt_maybe(value: str | None) -> datetime | None:
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None

    # よくあるISO形式のZ
    s = s.replace("Z", "+00:00")

    # "YYYY-mm-dd HH:MM:SS" 形式が来ることがある（スクショの pubdate がこれ）
    # タイムゾーン情報が無い場合は「JST想定 → UTC変換」して返す
    try:
        # fromisoformatは "YYYY-mm-dd HH:MM:SS" も通る
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            if ZoneInfo is not None:
                dt = dt.replace(tzinfo=ZoneInfo("Asia/Tokyo"))
            else:
                # zoneinfo が無い環境ならUTC扱いにする（誤差は出るが壊れない）
                dt = dt.replace(tzinfo=timezone.utc)
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
    '45230' のような5桁が来ることがあるので末尾4桁に寄せる。
    4桁のときはそのまま。
    """
    s = (company_code or "").strip()
    if not s.isdigit():
        return ""
    if len(s) == 4:
        return s
    if len(s) >= 4:
        return s[-4:]
    return ""


def _normalize_item(raw: dict[str, Any]) -> dict[str, Any]:
    td = _pick_tdnet_dict(raw)

    title = td.get("title") or td.get("Title") or ""
    # company_code / code が揺れる
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
    published_at = _parse_dt_maybe(published_raw)

    company_code_s = str(company_code) if company_code is not None else ""
    code4 = _code4_from_company_code(company_code_s)

    return {
        "title": str(title),
        "company_code": company_code_s,
        "code4": code4,
        "company_name": str(company_name),
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
