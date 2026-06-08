"""单次联调用例：打印 approve 相关错误与链接类型。"""
from __future__ import annotations

import json
import re
import sys

import requests

CHECKOUT = "http://bj2m1188418-region-JP:nanno2@127.0.0.1:3010"


def proxy_region(base: str, region: str) -> str:
    return re.sub(r"region-[A-Za-z]{2}", f"region-{region}", base)


def classify(url: str) -> str:
    if "paypal.com/agreements/approve" in url:
        return "paypal_ba"
    if "pay.openai.com/c/pay/cs_live" in url or "checkout.stripe.com/c/pay/cs_live" in url:
        return "hosted_only"
    return "other"


def strategy_profile(strategy: str) -> dict[str, str]:
    if strategy in {"de", "de_eur"}:
        return {"billing": "DE", "checkout": "DE", "provider": "DE", "locale": "de", "payment_strategy": "de_eur"}
    return {"billing": "US", "checkout": "JP", "provider": "US", "locale": "en", "payment_strategy": "jp_us"}


def main() -> int:
    if len(sys.argv) < 5:
        print("usage: _run_case.py <session_path> <billing|strategy> <provider_region|-> <label>")
        return 2
    session_path, billing_or_strategy, provider_region, label = sys.argv[1:5]
    session = open(session_path, encoding="utf-8").read().strip()
    if billing_or_strategy in {"jp_us", "de_eur", "de", "jp"}:
        profile = strategy_profile(billing_or_strategy)
        billing = profile["billing"]
        checkout_proxy = proxy_region(CHECKOUT, profile["checkout"])
        provider_proxy = proxy_region(CHECKOUT, profile["provider"])
        payment_strategy = profile["payment_strategy"]
        payment_locale = profile["locale"]
    else:
        billing = billing_or_strategy
        checkout_proxy = CHECKOUT
        provider_proxy = proxy_region(CHECKOUT, provider_region) if provider_region != "-" else CHECKOUT
        payment_strategy = "de_eur" if billing == "DE" else "jp_us"
        payment_locale = "de" if billing == "DE" else "en"
    payload = {
        "accessToken": session,
        "link_type": "paypal",
        "billing_country": billing,
        "payment_locale": payment_locale,
        "paymentStrategy": payment_strategy,
        "proxy": checkout_proxy,
        "checkoutProxy": checkout_proxy,
        "providerProxy": provider_proxy,
        "maxRetries": 2,
        "approveRetries": 15,
        "approvePoolSize": 30,
        "approvePoolMaxAttempts": 400,
    }
    print(f"=== {label} ===")
    print(json.dumps({"billing": billing, "payment_strategy": payment_strategy, "checkout_proxy": checkout_proxy, "provider_proxy": provider_proxy}, ensure_ascii=False))
    r = requests.post("http://127.0.0.1:8788/api/long-link", json=payload, timeout=1200)
    print("http", r.status_code)
    if not r.headers.get("content-type", "").startswith("application/json"):
        print(r.text[:500])
        return 1
    data = r.json()
    url = str(data.get("long_url") or "")
    err = str(data.get("provider_error") or "")
    out = {
        "ok": data.get("ok"),
        "cs_id": data.get("cs_id"),
        "billing_country": data.get("billing_country"),
        "currency": data.get("currency"),
        "approve_result": data.get("approve_result"),
        "url_type": classify(url),
        "provider_error": err[:300],
        "long_url_head": url[:200],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["url_type"] == "paypal_ba" else 1


if __name__ == "__main__":
    raise SystemExit(main())