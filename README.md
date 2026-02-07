# stock-kessan-screener

スマホからStreamlitにアクセスして、決算短信をスクリーニング→AIで要点と数値をJSON化→簡易可視化します。
壊れづらさ重視：HTMLスクレイピングはせず、TDnetの「一覧取得」はJSONインデックスを利用します。
AI要約は押した時だけ実行し、SQLiteにキャッシュします。

## 1) ローカル実行

Python 3.11推奨

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
