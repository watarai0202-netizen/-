from __future__ import annotations

from typing import Any, Dict, Optional

import streamlit as st


def _get(d: Dict[str, Any], *keys: str, default=None):
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


def _as_number(x: Any) -> Optional[float]:
    if isinstance(x, (int, float)):
        return float(x)
    return None


def _pct_to_bar_dict(yoy: dict) -> dict:
    out = {}
    for key, label in [
        ("sales", "売上YoY%"),
        ("op_profit", "営業利益YoY%"),
        ("ordinary_profit", "経常利益YoY%"),
        ("net_profit", "純利益YoY%"),
    ]:
        v = _as_number(yoy.get(key))
        if v is not None:
            out[label] = v
    return out


def render_analysis(payload: dict) -> None:
    """
    旧スキーマ（summary_1min/headline/performance...）と
    新スキーマ（analyzer.py: {ok, pdf_url, model, tokens, result:{...}}）の両方に対応。
    """

    if not isinstance(payload, dict):
        st.error("解析結果の形式が不正です（dictではありません）。")
        return

    # --- 新スキーマ判定（payload["result"] に要約JSON）---
    new_result = payload.get("result") if isinstance(payload.get("result"), dict) else None

    # --- 旧スキーマ判定 ---
    has_old = any(k in payload for k in ("summary_1min", "headline", "watch_points"))

    # ----------------------------
    # Header meta
    # ----------------------------
    if payload.get("ok") is False:
        st.error(payload.get("error") or "解析に失敗しました。")
        return

    pdf_url = payload.get("pdf_url")
    model = payload.get("model")
    tokens = payload.get("tokens")

    meta = {}
    if pdf_url:
        meta["pdf_url"] = pdf_url
    if model:
        meta["model"] = model
    if tokens is not None:
        meta["tokens"] = tokens
    if meta:
        st.caption(meta)

    # ============================
    # ✅ 新スキーマ表示
    # ============================
    if new_result is not None:
        # 1分要約（summary）
        st.markdown("#### 1分要約")
        st.write(new_result.get("summary") or "")

        # パフォーマンス
        perf = new_result.get("performance") or {}
        if not isinstance(perf, dict):
            perf = {}

        st.markdown("#### 業績ハイライト（主要数値）")
        st.write(
            {
                "売上": _get(perf, "sales"),
                "営業利益": _get(perf, "op_profit"),
                "経常利益": _get(perf, "ordinary_profit"),
                "純利益": _get(perf, "net_profit"),
            }
        )

        # YoY（%）
        yoy = perf.get("yoy") or {}
        if not isinstance(yoy, dict):
            yoy = {}

        st.markdown("#### 前年比（%）")
        yoy_bar = _pct_to_bar_dict(yoy)
        if yoy_bar:
            st.bar_chart(yoy_bar)
        else:
            st.info("前年比（%）が取得できませんでした。")

        # 進捗（%）
        prog = perf.get("progress_full_year") or {}
        if not isinstance(prog, dict):
            prog = {}

        st.markdown("#### 通期進捗（%）")
        prog_bar = {}
        for key, label in [
            ("sales", "売上進捗%"),
            ("op_profit", "営業利益進捗%"),
            ("ordinary_profit", "経常利益進捗%"),
            ("net_profit", "純利益進捗%"),
        ]:
            v = _as_number(prog.get(key))
            if v is not None:
                prog_bar[label] = v
        if prog_bar:
            st.bar_chart(prog_bar)
        else:
            st.info("通期進捗（%）が取得できませんでした。")

        # 修正有無
        rev = perf.get("revision") or {}
        if not isinstance(rev, dict):
            rev = {}

        st.markdown("#### 修正（上方/下方/据置）")
        st.write(
            {
                "修正あり": rev.get("exists"),
                "方向": rev.get("direction"),
                "理由": rev.get("reason"),
            }
        )

        # ガイダンス（通期予想）
        guide = new_result.get("guidance") or {}
        if not isinstance(guide, dict):
            guide = {}

        fy = guide.get("full_year_forecast") or {}
        if not isinstance(fy, dict):
            fy = {}

        st.markdown("#### ガイダンス（通期予想）")
        st.write(
            {
                "売上予想": fy.get("sales"),
                "営業利益予想": fy.get("op_profit"),
                "経常利益予想": fy.get("ordinary_profit"),
                "純利益予想": fy.get("net_profit"),
                "前提": guide.get("assumptions") or [],
                "注記": guide.get("notes") or "",
            }
        )

        # 注目ポイント / リスク / 次に見る資料
        st.markdown("#### 注目ポイント")
        st.write(new_result.get("highlights") or [])

        st.markdown("#### リスク / 懸念")
        st.write(new_result.get("risks") or [])

        st.markdown("#### 次に見るべき資料")
        st.write(new_result.get("next_to_check") or [])

        return

    # ============================
    # ✅ 旧スキーマ表示（後方互換）
    # ============================
    if has_old:
        # 1分要約
        st.markdown("#### 1分要約")
        st.write(payload.get("summary_1min", ""))

        # トーン/スコア
        headline = payload.get("headline") or {}
        tone = headline.get("tone", "不明") if isinstance(headline, dict) else "不明"
        score = headline.get("score_0_10", None) if isinstance(headline, dict) else None
        st.markdown("#### トーン / スコア")
        st.write(f"トーン: {tone} / スコア: {score}")

        # YoY
        perf = payload.get("performance") or {}
        st.markdown("#### 前年比（%）")
        numeric = {}
        if isinstance(perf, dict):
            for k in ["sales_yoy_pct", "op_yoy_pct", "ordinary_yoy_pct", "net_yoy_pct"]:
                v = perf.get(k)
                if isinstance(v, (int, float)):
                    numeric[k] = v

        if numeric:
            st.bar_chart(numeric)
        else:
            st.info("前年比の数値が取れませんでした（書式差の可能性）。")

        # ガイダンス
        guide = payload.get("guidance") or {}
        st.markdown("#### ガイダンス")
        st.write(
            {
                "raised": guide.get("raised") if isinstance(guide, dict) else None,
                "lowered": guide.get("lowered") if isinstance(guide, dict) else None,
                "unchanged": guide.get("unchanged") if isinstance(guide, dict) else None,
                "sales_full_year": guide.get("sales_full_year") if isinstance(guide, dict) else None,
                "op_full_year": guide.get("op_full_year") if isinstance(guide, dict) else None,
                "eps_full_year": guide.get("eps_full_year") if isinstance(guide, dict) else None,
            }
        )

        # 理由/リスク
        drivers = payload.get("drivers") or {}
        risks = payload.get("risks") or {}
        st.markdown("#### 増減益理由")
        st.write("増益理由:", drivers.get("profit_up_reasons", []) if isinstance(drivers, dict) else [])
        st.write("減益理由:", drivers.get("profit_down_reasons", []) if isinstance(drivers, dict) else [])

        st.markdown("#### リスク")
        st.write("短期:", risks.get("short_term", []) if isinstance(risks, dict) else [])
        st.write("中期:", risks.get("mid_term", []) if isinstance(risks, dict) else [])

        st.markdown("#### ウォッチポイント")
        st.write(payload.get("watch_points", []))
        return

    # どっちでもない
    st.warning("解析結果のスキーマが想定外です。payload を確認してください。")
    st.json(payload)
