import os
from datetime import datetime, timedelta, timezone

import streamlit as st

from src.tdnet import fetch_tdnet_items
from src.analyzer import analyze_pdf_to_json, ai_is_enabled
from src.storage import init_db, get_cached_analysis, save_analysis, db_path_default
from src.viz import render_analysis

# ----------------------------
# Page
# ----------------------------
st.set_page_config(page_title="決算短信スクリーナー", layout="wide")

# ----------------------------
# Auth (simple password gate)
# ----------------------------
APP_PASSWORD = st.secrets.get("APP_PASSWORD", "")
if not APP_PASSWORD:
    st.error("APP_PASSWORD が未設定です（Secretsに設定してください）")
    st.stop()

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("認証が必要です")
    pw = st.text_input("パスワード", type="password")
    if pw == APP_PASSWORD:
        st.session_state.authenticated = True
        st.rerun()
    st.stop()

# ----------------------------
# DB init (cache store)
# ----------------------------
DB_PATH = st.secrets.get("DB_PATH", db_path_default())
init_db(DB_PATH)

# ----------------------------
# Header
# ----------------------------
st.title("📈 決算短信スクリーニング & ビジュアライズ")
st.caption("狙い：スマホでも「銘柄→決算→要点＋数値」まで最短で見る。AI要約は押した時だけ実行。")

# ----------------------------
# Screening controls
# ----------------------------
with st.expander("スクリーニング条件", expanded=True):
    col1, col2, col3 = st.columns([2, 2, 2])

    with col1:
        code = st.text_input("銘柄コード（4桁、空なら直近全体）", value="").strip()
        only_kessan = st.checkbox("決算短信だけに絞る", value=True)

    with col2:
        days = st.slider("直近何日を見る？", 1, 14, 3)
        limit = st.slider("取得件数（大きいほど遅い）", 50, 500, 200)

    with col3:
        only_has_doc_url = st.checkbox("PDF URLがあるものだけ", value=True)
        show_ai_button = st.checkbox("AI分析ボタンを表示", value=True)

# sanity for code
if code and (not code.isdigit() or len(code) != 4):
    st.warning("銘柄コードは4桁の数字で入力してください（例：7203）")
    code = ""

# ----------------------------
# Fetch TDnet index (non-scrape)
# ----------------------------
cutoff_utc = datetime.now(timezone.utc) - timedelta(days=days)
with st.spinner("開示一覧を取得中..."):
    items = fetch_tdnet_items(code or None, limit=limit)

# Filter
filtered = []
for it in items:
    title = (it.get("title") or "").strip()
    doc_url = (it.get("doc_url") or "").strip()
    published = it.get("published_at")

    if only_kessan and "決算短信" not in title:
        continue
    if only_has_doc_url and not doc_url:
        continue
    if published and published < cutoff_utc:
        continue

    filtered.append(it)

st.subheader(f"候補：{len(filtered)}件")
if not filtered:
    st.info("条件に一致する開示が見つかりませんでした。日数や件数を広げてください。")
    st.stop()

# AI availability
ai_ok = ai_is_enabled()
if show_ai_button and not ai_ok:
    st.warning("Gemini APIキー未設定のため、AI分析は無効です（数値表示のみ）。Secretsに GEMINI_API_KEY を設定してください。")

# ----------------------------
# Render list
# ----------------------------
# スマホ前提：1件ずつexpanderで開く UI
for it in filtered[:100]:
    title = it.get("title", "")
    code_ = it.get("code", "")
    doc_url = it.get("doc_url", "")
    published = it.get("published_at")
    published_str = published.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if published else "不明"

    label = f"{code_}｜{published_str}｜{title}"
    with st.expander(label, expanded=False):
        st.caption(f"PDF: {doc_url}")

        cached = get_cached_analysis(DB_PATH, doc_url) if doc_url else None
        if cached:
            st.success("解析済み（キャッシュ）")
            render_analysis(cached)
        else:
            st.info("未解析")

        cols = st.columns([1, 1, 2])
        with cols[0]:
            if st.button("キャッシュ表示", key=f"show_{doc_url}") and cached:
                render_analysis(cached)
        with cols[1]:
            can_run_ai = show_ai_button and ai_ok and bool(doc_url)
            run = st.button("AI分析", key=f"ai_{doc_url}", disabled=not can_run_ai)
        with cols[2]:
            st.caption("※同じPDF URLはSQLiteに保存し、再解析しません（DBはキャッシュ扱い）。")

        if run:
            with st.spinner("AIが決算短信を解析中..."):
                try:
                    payload = analyze_pdf_to_json(doc_url)
                    save_analysis(DB_PATH, doc_url, code_, title, published, payload)
                    st.success("解析完了")
                    render_analysis(payload)
                except Exception as e:
                    st.error(f"解析エラー: {type(e).__name__}: {e}")

st.divider()

# Manual analyze
st.subheader("手動解析（PDF URLを貼る）")
manual = st.text_input("PDF URL（.pdf推奨）", value="").strip()
colA, colB = st.columns([1, 3])
with colA:
    manual_run = st.button("AI解析", disabled=not (ai_ok and manual))
with colB:
    st.caption("※PDF以外のURLだと失敗します（HTMLなど）。")

if manual_run:
    with st.spinner("AIが解析中..."):
        payload = analyze_pdf_to_json(manual)
    st.json(payload)
