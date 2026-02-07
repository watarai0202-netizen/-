from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests

# 非スクレイピングのJSONインデックス（やのしん TDnet WEB-API）
TDNET_BASE = "https://webapi.yanoshin.jp/webapi/tdnet/list"


def _parse_dt_maybe(value: str | None) -> datetime | None:
    if not value:
        return None
    s = str(value).strip()
    s = s.replace("Z", "+00:00")
    # "YYYY-MM-DD HH:MM:SS" も来るのでISO寄せ
    if " " in s and "T" not in s:
        s = s.replace(" ", "T")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _to_code4(company_code: str | None, code: str | None) -> str:
    """
    TDnet側の company_code は 5桁（例: 45230）が混ざるので、
    日本株の4桁コード（例: 4523）に寄せる。
    """
    if code and str(code).isdigit() and len(str(code)) == 4:
        return str(code)

    cc = (company_code or "").strip()
    if cc.isdigit():
        if len(cc) == 5 and cc.endswith("0"):
            return cc[:4]
        if len(cc) == 4:
            return cc
    return ""


def _unwrap_doc_url(url: str) -> str:
    """
    例:
    https://webapi.yanoshin.jp/rd.php?https://www.release.tdnet.info/inbs/xxx.pdf
    のような rd.php 形式を TDnetのPDF直リンクに戻す。
    """
    u = (url or "").strip()
    if not u:
        return ""

    # 典型: rd.php?https://....
    if "webapi.yanoshin.jp/rd.php?" in u:
        try:
            return u.split("rd.php?", 1)[1].strip()
        except Exception:
            return u

    return u


def _normalize_item(raw: dict[str, Any]) -> dict[str, Any]:
    """
    APIレスポンスの揺れに耐える正規化。
    """
    td = raw.get("TDnet") if isinstance(raw.get("TDnet"), dict) else raw

    title = td.get("title") or td.get("Title") or ""
    company_name = td.get("company_name") or td.get("companyName") or ""

    # 4桁/5桁の揺れ対策
    company_code = str(td.get("company_code") or td.get("companyCode") or td.get("code") or "").strip()
    code = str(td.get("code") or td.get("Code") or "").strip()
    code4 = _to_code4(company_code, code)

    doc_url = (
        td.get("document_url")
        or td.get("documentUrl")
        or td.get("doc_url")
        or td.get("url")
        or ""
    )
    doc_url = _unwrap_doc_url(str(doc_url))

    published_raw = td.get("published_at") or td.get("pubdate") or td.get("date") or ""
    published_at = _parse_dt_maybe(str(published_raw))

    # link というキーを使ってる古いコードがあっても壊れないように
    link = td.get("link") or ""

    return {
        "title": str(title),
        "company_name": str(company_name),
        "company_code": company_code,
        "code": code4,  # UIではこれを主に使う（4桁）
        "code4": code4,
        "doc_url": str(doc_url),
        "link": str(link),
        "published_at": published_at,
        "raw": td,
    }


def fetch_tdnet_items(code: str | None, limit: int = 200) -> list[dict[str, Any]]:
    """
    code があれば銘柄別、なければ recent。
    """
    code = (code or "").strip()
    if code.isdigit() and len(code) == 4:
        url = f"{TDNET_BASE}/{code}.json?limit={limit}"
    else:
        url = f"{TDNET_BASE}/recent.json?limit={limit}"

    r = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    data = r.json()

    items = data.get("items")
    if not isinstance(items, list):
        return []

    out: list[dict[str, Any]] = []
    for raw in items:
        if isinstance(raw, dict):
            out.append(_normalize_item(raw))
    return out
