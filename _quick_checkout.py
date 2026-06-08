"""快速探测 checkout 能否创建（不跑完整 PP 链）。"""
import json
import re
import sys
import requests

BASE_PROXY = "http://bj2m1188418-region-JP:nanno2@127.0.0.1:3010"


def pr(region: str) -> str:
    return re.sub(r"region-[A-Za-z]{2}", f"region-{region}", BASE_PROXY)


def main() -> None:
    session_path, billing, checkout_r, label = sys.argv[1:5]
    session = open(session_path, encoding="utf-8").read().strip()
    payload = {
        "accessToken": session,
        "link_type": "paypal",
        "billing_country": billing,
        "payment_locale": "de" if billing == "DE" else "en",
        "paymentStrategy": "de_eur" if billing == "DE" else "jp_us",
        "proxy": pr(checkout_r),
        "checkoutProxy": pr(checkout_r),
        "providerProxy": pr(sys.argv[4] if len(sys.argv) > 4 else checkout_r),
        "maxRetries": 1,
        "approvePoolSize": 5,
        "approvePoolMaxAttempts": 20,
    }
    if len(sys.argv) > 5:
        payload["providerProxy"] = pr(sys.argv[5])
    print(label, json.dumps({"billing": billing, "checkout": checkout_r, "provider": payload["providerProxy"]}, ensure_ascii=False))
    r = requests.post("http://127.0.0.1:8788/api/long-link", json=payload, timeout=300)
    d = r.json()
    print(json.dumps({
        "http": r.status_code,
        "ok": d.get("ok"),
        "cs_id": d.get("cs_id"),
        "billing": d.get("billing_country"),
        "currency": d.get("currency"),
        "approve": d.get("approve_result"),
        "url": (d.get("long_url") or "")[:120],
        "err": (d.get("provider_error") or "")[:200],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()