"""多策略矩阵：对两个 session 批量测试 PP 链。"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

BASE = "http://bj2m1188418-region-JP:nanno2@127.0.0.1:3010"
API = "http://127.0.0.1:8788/api/long-link"
OUT = Path(__file__).with_name("_test_matrix_results.jsonl")

STRATEGIES = [
    "de_eur",
    "de_billing_us_provider",
    "jp_de_billing",
    "jp_us",
]

SESSIONS = [
    ("session1", Path("测试session/session1.txt")),
    ("session2", Path("测试session/session2.txt")),
]


def classify(url: str) -> str:
    if "paypal.com/agreements/approve" in url:
        return "paypal_ba"
    if "pay.openai.com" in url or "checkout.stripe.com" in url:
        return "hosted_only"
    return "other"


def run_case(session_name: str, session_path: Path, strategy: str) -> dict:
    session = session_path.read_text(encoding="utf-8").strip()
    payload = {
        "accessToken": session,
        "link_type": "paypal",
        "paymentStrategy": strategy,
        "proxy": BASE,
        "checkoutProxy": BASE,
        "providerProxy": BASE,
        "maxRetries": 2,
        "approvePoolSize": 30,
        "approvePoolMaxAttempts": 600,
    }
    t0 = time.time()
    try:
        r = requests.post(API, json=payload, timeout=420)
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    except Exception as exc:
        data = {"provider_error": str(exc)}
        r = None
    url = str(data.get("long_url") or "")
    row = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "session": session_name,
        "strategy": strategy,
        "http": getattr(r, "status_code", 0),
        "ok": data.get("ok"),
        "cs_id": data.get("cs_id"),
        "billing_country": data.get("billing_country"),
        "currency": data.get("currency"),
        "approve_result": data.get("approve_result"),
        "url_type": classify(url),
        "ba_token": "",
        "long_url": url[:240],
        "provider_error": str(data.get("provider_error") or "")[:300],
        "elapsed_s": round(time.time() - t0, 1),
    }
    if "ba_token=" in url:
        row["ba_token"] = url.split("ba_token=", 1)[1].split("&", 1)[0][:40]
    return row


def main() -> None:
    results: list[dict] = []
    for session_name, session_path in SESSIONS:
        for strategy in STRATEGIES:
            label = f"{session_name}:{strategy}"
            print("RUN", label, flush=True)
            row = run_case(session_name, session_path, strategy)
            results.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            with OUT.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            if row["url_type"] == "paypal_ba":
                print("SUCCESS", label, row.get("ba_token"), flush=True)
                return
    print("NO_BA_FOUND", flush=True)


if __name__ == "__main__":
    main()