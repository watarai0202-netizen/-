from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Optional, Tuple

import requests

# PDF抽出（requirements: pypdf）
try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None  # type: ignore

# Gemini SDK（requirements: google-genai）
try:
    from google import genai
except Exception:
    genai = None  # type: ignore


# ----------------------------
# Public API (used by app.py)
# ----------------------------

def ai_is_enabled() -> bool:
    """Gemini APIキーが設定されているか（Secrets/ENV両対応想定）"""
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    return bool(key)


def analyze_pdf_to_json(
    pdf_url: str,
    *,
    gemini_api_key: Optional[str] = None,
    gemini_model: Optional[str] = None,
    max_pdf_bytes: Optional[int] = None,
) -> dict[str, Any]:
    """
    app.py から呼ばれる想定。
    決算短信PDFをDL→テキスト抽出→GeminiでJSON要約→dictで返す。
    """
    key = (gemini_api_key or os.getenv("GEMINI_API_KEY") or "").strip()
    model = (gemini_model or os.getenv("GEMINI_MODEL") or "gemini-2.0-flash").strip()
    limit = int(max_pdf_bytes or (os.getenv("MAX_PDF_BYTES") or 0) or 0)
    if limit <= 0:
        # 無指定時の安全なデフォルト（20MB）
        limit = 20 * 1024 * 1024

    res = summarize_kessan_pdf_to_json(
        pdf_url=pdf_url,
        gemini_api_key=key,
        gemini_model=model,
        max_pdf_bytes=limit,
    )

    if not res.ok:
        # render側が落ちないよう、エラーでも一定の形で返す
        return {
            "ok": False,
            "error": res.error,
            "model": model,
            "pdf_url": pdf_url,
        }

    return res.payload


# ----------------------------
# Internal data structures
# ----------------------------

@dataclass
class AnalyzeResult:
    ok: bool
    error: str = ""
    tokens: Optional[int] = None
    payload: Optional[dict[str, Any]] = None


# ----------------------------
# PDF: download + extract
# ----------------------------

def download_pdf(url: str, max_bytes: int) -> tuple[bytes | None, str]:
    """
    PDFをダウンロード。サイズ上限を超えたら止める。
    """
    u = (url or "").strip()
    if not u:
        return None, "PDF URLが空です。"

    try:
        with requests.get(
            u,
            stream=True,
            timeout=35,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as r:
            r.raise_for_status()

            total = 0
            chunks: list[bytes] = []

            for chunk in r.iter_content(chunk_size=1024 * 128):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    return None, f"PDFサイズが上限を超えました（>{max_bytes} bytes）"
                chunks.append(chunk)

            return b"".join(chunks), ""
    except Exception as e:
        return None, f"PDFダウンロード失敗: {e}"


def extract_text_from_pdf_bytes(pdf_bytes: bytes, max_pages: int = 35) -> tuple[str, str]:
    """
    返り値: (text, err)
    """
    if PdfReader is None:
        return "", "PDF抽出ライブラリ(pypdf)が未インストールです。requirements に `pypdf` を追加してください。"

    try:
        import io

        reader = PdfReader(io.BytesIO(pdf_bytes))

        # 暗号化PDF対策（パス無しで開けるケースだけ try）
        try:
            if getattr(reader, "is_encrypted", False):
                reader.decrypt("")  # type: ignore
        except Exception:
            pass

        texts: list[str] = []
        pages = reader.pages[:max_pages]
        for p in pages:
            t = p.extract_text() or ""
            if t.strip():
                texts.append(t)

        out = "\n\n".join(texts).strip()
        if not out:
            return "", "PDFからテキストを抽出できませんでした（空）。図表中心PDFの可能性があります。"
        return out, ""
    except Exception as e:
        return "", f"PDF抽出に失敗しました: {e}"


# ----------------------------
# Gemini: generate JSON
# ----------------------------

def _gemini_generate_json(
    api_key: str,
    model: str,
    prompt: str,
    *,
    temperature: float = 0.2,
    max_retries: int = 3,
    retry_sleep: float = 1.2,
) -> Tuple[Optional[dict[str, Any]], Optional[int], str]:
    """
    google-genai SDKで application/json を返させる。
    返り値: (json_dict, tokens, err)
    """
    api_key = (api_key or "").strip()
    if not api_key:
        return None, None, "GEMINI_API_KEY が未設定です。"
    if genai is None:
        return None, None, "google-genai が未インストールです。requirements.txt を確認してください。"

    model = (model or "").strip() or "gemini-2.0-flash"

    # SDKクライアント
    client = genai.Client(api_key=api_key)

    last_err = ""
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config={
                    "temperature": float(temperature),
                    # JSONで返させる（重要）
                    "response_mime_type": "application/json",
                },
            )

            # google-genaiの返却は resp.text に JSON文字列が入ることが多い
            raw = (getattr(resp, "text", None) or "").strip()
            if not raw:
                return None, None, "Geminiの返答が空です。"

            # JSONパース
            try:
                obj = json.loads(raw)
            except Exception:
                # たまに ```json ... ``` で返すモデルがあるので救済
                cleaned = raw.strip().strip("`")
                cleaned = cleaned.replace("json\n", "", 1) if cleaned.lower().startswith("json\n") else cleaned
                try:
                    obj = json.loads(cleaned)
                except Exception:
                    return None, None, f"GeminiのJSONパースに失敗しました。先頭: {raw[:200]}"

            # トークン（取れる時だけ）
            tokens = None
            usage = getattr(resp, "usage_metadata", None)
            if usage is not None:
                # usage_metadataの形が環境で変わるので雑に拾う
                tokens = getattr(usage, "total_token_count", None) or getattr(usage, "total_tokens", None)

            return obj, tokens, ""

        except Exception as e:
            last_err = str(e)
            # 軽いリトライ（429/503などを想定）
            if attempt < max_retries:
                time.sleep(retry_sleep * attempt)
                continue
            break

    return None, None, f"Gemini呼び出し失敗: {last_err}"


# ----------------------------
# Main summarizer
# ----------------------------

def summarize_kessan_pdf_to_json(
    pdf_url: str,
    gemini_api_key: str,
    gemini_model: str,
    max_pdf_bytes: int,
) -> AnalyzeResult:
    pdf_bytes, err = download_pdf(pdf_url, max_bytes=max_pdf_bytes)
    if pdf_bytes is None:
        return AnalyzeResult(ok=False, error=err)

    text, err = extract_text_from_pdf_bytes(pdf_bytes, max_pages=35)
    if err:
        return AnalyzeResult(ok=False, error=err)

    # 入れすぎると遅い・コスト増なので上限を設ける（必要なら調整）
    text = text[:160000]

    prompt = f"""
あなたは日本株の決算短信を読むプロのアナリストです。
以下はTDnetの決算短信PDFから抽出したテキストです。
投資判断に使えるように「必ずJSONのみ」で整理してください。

【出力ルール】
- 出力は JSON オブジェクトのみ（説明文やMarkdown禁止）
- 文字列は日本語
- 数値は可能なら number（不明なら null）
- YOY/進捗/修正など、見つかったものだけ埋める（不明は null）
- 文章は短く、箇条書きは配列にする

【JSONスキーマ（厳守）】
{{
  "ok": true,
  "summary": "3行以内",
  "performance": {{
    "sales": null,
    "op_profit": null,
    "ordinary_profit": null,
    "net_profit": null,
    "yoy": {{
      "sales": null,
      "op_profit": null,
      "ordinary_profit": null,
      "net_profit": null
    }},
    "progress_full_year": {{
      "sales": null,
      "op_profit": null,
      "ordinary_profit": null,
      "net_profit": null
    }},
    "revision": {{
      "exists": null,
      "direction": null,
      "reason": null
    }}
  }},
  "guidance": {{
    "full_year_forecast": {{
      "sales": null,
      "op_profit": null,
      "ordinary_profit": null,
      "net_profit": null
    }},
    "assumptions": ["..."],
    "notes": "..."
  }},
  "highlights": ["..."],
  "risks": ["..."],
  "next_to_check": ["..."]
}}

【テキスト】
{text}
""".strip()

    obj, tokens, err = _gemini_generate_json(
        api_key=gemini_api_key,
        model=gemini_model,
        prompt=prompt,
        temperature=0.2,
        max_retries=3,
    )
    if obj is None:
        return AnalyzeResult(ok=False, error=err)

    # 最低限のメタを付与（vizやDBで便利）
    payload: dict[str, Any] = {
        "ok": True,
        "pdf_url": pdf_url,
        "model": gemini_model,
        "tokens": tokens,
        "result": obj,
    }
    return AnalyzeResult(ok=True, payload=payload, tokens=tokens)
