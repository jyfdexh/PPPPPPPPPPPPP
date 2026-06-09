"""联调：DE 账单 + JP checkout + DE provider + JP approve（对齐 oaipay 成功案例）。"""
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
    session = open(session_path, encoding="utf-8").read().strip()
    payload = {
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
        "approvePoolSize": 30,
        "approvePoolMaxAttempts": 600,
    }
    print("payload", json.dumps({
        "billing": "DE",
        "checkout": payload["checkoutProxy"],
        "provider": payload["providerProxy"],
        "approve": payload["approveProxy"],
    }, ensure_ascii=False))
    r = requests.post("http://127.0.0.1:8788/api/long-link", json=payload, timeout=110)
    print("http", r.status_code)
    data = r.json()
    url = str(data.get("long_url") or "")
    print(json.dumps({
        "ok": data.get("ok"),
        "cs_id": data.get("cs_id"),
        "billing_country": data.get("billing_country"),
        "currency": data.get("currency"),
        "processor_entity": data.get("processor_entity"),
        "approve_result": data.get("approve_result"),
        "fallback": data.get("fallback"),
        "provider_error": str(data.get("provider_error") or "")[:300],
        "stripe_redirect_head": str(data.get("stripe_redirect_url") or "")[:120],
        "provider_redirect_head": str(data.get("provider_redirect_url") or "")[:120],
        "long_url_head": url[:120],
        "is_ba": "paypal.com/agreements/approve" in url,
    }, ensure_ascii=False, indent=2))
    return 0 if data.get("ok") and "paypal.com/agreements/approve" in url else 1


if __name__ == "__main__":
    raise SystemExit(main())