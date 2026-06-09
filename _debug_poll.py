"""调试：approve 后打印 payment_pages / setup_intent 关键字段。"""
from __future__ import annotations

import json
import re
import sys

import requests

CHECKOUT = "http://bj2m1188418-region-JP:nanno2@127.0.0.1:3010"


def proxy_region(base: str, region: str) -> str:
    return re.sub(r"region-[A-Za-z]{2}", f"region-{region}", base)


def main() -> int:
    session_path = sys.argv[1] if len(sys.argv) > 1 else r"测试session\session1.txt"
    strategy = sys.argv[2] if len(sys.argv) > 2 else "jp_us"
    session = open(session_path, encoding="utf-8").read().strip()
    profiles = {
        "jp_us": ("US", "JP", "US", "JP", "jp_us"),
        "jp_de": ("DE", "JP", "DE", "JP", "jp_de"),
        "de_eur": ("DE", "JP", "DE", "JP", "jp_de"),
    }
    billing, checkout_r, provider_r, approve_r, payment_strategy = profiles.get(strategy, profiles["jp_us"])
    payload = {
        "accessToken": session,
        "link_type": "paypal",
        "billing_country": billing,
        "payment_locale": "de" if billing == "DE" else "en",
        "paymentStrategy": payment_strategy,
        "approveProxyRegion": approve_r,
        "proxy": proxy_region(CHECKOUT, checkout_r),
        "checkoutProxy": proxy_region(CHECKOUT, checkout_r),
        "providerProxy": proxy_region(CHECKOUT, provider_r),
        "approveProxy": proxy_region(CHECKOUT, approve_r),
        "maxRetries": 1,
        "approveRetries": 10,
        "approvePoolSize": 15,
        "approvePoolMaxAttempts": 200,
    }
    print("payload", json.dumps({k: payload[k] for k in ("paymentStrategy", "billing_country", "checkoutProxy", "providerProxy")}, ensure_ascii=False))
    with requests.post(
        "http://127.0.0.1:8788/api/long-link/stream",
        json=payload,
        stream=True,
        timeout=900,
    ) as resp:
        print("http", resp.status_code)
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                print(line[:300])
                continue
            step = str(event.get("step") or "")
            message = str(event.get("message") or "")
            if step in {"redirect_poll", "chatgpt_approve", "provider_redirect", "fallback", "done"} or "redirect" in message.lower():
                print(json.dumps(event, ensure_ascii=False)[:500])
            if event.get("event") == "result":
                print("RESULT", json.dumps(event, ensure_ascii=False)[:1200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())