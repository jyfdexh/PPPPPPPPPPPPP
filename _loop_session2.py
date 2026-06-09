"""循环测试 session2：DE + JP approve，单轮超过 60 秒即失败并进入下一轮。"""
from __future__ import annotations

import json
import re
import sys
import time

import requests

CHECKOUT = "http://bj2m1188418-region-JP:nanno2@127.0.0.1:3010"
API = "http://127.0.0.1:8788/api/long-link"
SESSION = r"测试session\session2.txt"
ROUND_TIMEOUT = 65
MAX_ROUNDS = 20


def proxy_region(base: str, region: str) -> str:
    return re.sub(r"region-[A-Za-z]{2}", f"region-{region}", base)


def build_payload(session: str) -> dict:
    return {
        "accessToken": session,
        "link_type": "paypal",
        "billing_country": "DE",
        "payment_locale": "de",
        "paymentStrategy": "jp_de",
        "approveProxyRegion": "JP",
        "proxy": proxy_region(CHECKOUT, "JP"),
        "checkoutProxy": proxy_region(CHECKOUT, "JP"),
        "providerProxy": proxy_region(CHECKOUT, "DE"),
        "approveProxy": proxy_region(CHECKOUT, "JP"),
        "maxRetries": 1,
        "approveRetries": 10,
        "approvePoolSize": 4,
        "approvePoolMaxAttempts": 30,
    }


def main() -> int:
    session_path = sys.argv[1] if len(sys.argv) > 1 else SESSION
    max_rounds = int(sys.argv[2]) if len(sys.argv) > 2 else MAX_ROUNDS
    session = open(session_path, encoding="utf-8").read().strip()
    for round_no in range(1, max_rounds + 1):
        started = time.time()
        print(f"\n===== 第 {round_no}/{max_rounds} 轮 =====", flush=True)
        try:
            r = requests.post(API, json=build_payload(session), timeout=ROUND_TIMEOUT)
        except requests.Timeout:
            elapsed = time.time() - started
            print(f"超时失败（{elapsed:.1f}s > {ROUND_TIMEOUT}s）", flush=True)
            continue
        except Exception as exc:
            print(f"请求异常: {exc}", flush=True)
            continue
        elapsed = time.time() - started
        print(f"http={r.status_code} elapsed={elapsed:.1f}s", flush=True)
        if r.status_code != 200:
            print(r.text[:400], flush=True)
            continue
        try:
            data = r.json()
        except json.JSONDecodeError:
            print(r.text[:400], flush=True)
            continue
        url = str(data.get("long_url") or "")
        summary = {
            "ok": data.get("ok"),
            "cs_id": data.get("cs_id"),
            "billing_country": data.get("billing_country"),
            "currency": data.get("currency"),
            "approve_result": data.get("approve_result"),
            "fallback": data.get("fallback"),
            "provider_error": str(data.get("provider_error") or "")[:200],
            "stripe_redirect": str(data.get("stripe_redirect_url") or "")[:100],
            "provider_redirect": str(data.get("provider_redirect_url") or "")[:100],
            "long_url": url[:120],
            "is_ba": "paypal.com/agreements/approve" in url,
            "elapsed_s": round(elapsed, 1),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        if summary["is_ba"] and data.get("ok"):
            print("SUCCESS", flush=True)
            return 0
        if elapsed > 60:
            print("本轮超过 60 秒，视为失败。", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())