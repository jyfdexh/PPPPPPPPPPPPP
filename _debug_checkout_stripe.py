"""诊断 checkout → stripe init → payment_method → confirm 全链路。"""
from __future__ import annotations

import json
import re
import time

import app

CHECKOUT = "http://bj2m1188418-region-JP:nanno2@127.0.0.1:3010"
SESSION = r"测试session\session2.txt"


def proxy_region(base: str, region: str) -> str:
    return re.sub(r"region-[A-Za-z]{2}", f"region-{region}", base)


def main() -> None:
    session = open(SESSION, encoding="utf-8").read().strip()
    req = app.apply_payment_strategy(
        app.LongLinkRequest(
            accessToken=session,
            link_type="paypal",
            billing_country="DE",
            payment_locale="de",
            paymentStrategy="jp_de",
            approveProxyRegion="JP",
            checkoutProxy=proxy_region(CHECKOUT, "JP"),
            providerProxy=proxy_region(CHECKOUT, "DE"),
            approveProxy=proxy_region(CHECKOUT, "JP"),
        )
    )
    chatgpt = app.build_chatgpt_session(req)
    checkout = app.create_checkout(req, chatgpt)
    print("checkout", json.dumps(checkout, ensure_ascii=False))
    cs_id = checkout["cs_id"]
    stripe_pk_checkout = app.stripe_publishable_key_for(checkout, req)
    stripe_pk_default = app.DEFAULT_STRIPE_PK
    print(f"pk checkout={stripe_pk_checkout[:24]}... default={stripe_pk_default[:24]}... match={stripe_pk_checkout == stripe_pk_default}")

    time.sleep(0.35)
    provider_proxy = req.provider_proxy
    stripe = app.build_stripe_session(req, proxy_override=provider_proxy)
    init_payload = app.stripe_init(cs_id, req, proxy_override=provider_proxy, stripe_session=stripe, checkout=checkout)
    hosted = str(init_payload.get("stripe_hosted_url") or init_payload.get("url") or "")[:120]
    print("init OK", hosted)
    print("init_checksum", init_payload.get("init_checksum", "")[:40])
    print("config_id", init_payload.get("config_id", ""))

    ctx = app.stripe_context(cs_id, init_payload, req)
    billing = app.billing_for_link_type("paypal", checkout.get("billing_country", "DE"))
    try:
        pm_id = app.stripe_create_payment_method(stripe, cs_id, stripe_pk_checkout, billing, "paypal", ctx)
        print("pm OK", pm_id)
    except Exception as exc:
        print("pm FAIL", exc)
        return

    try:
        confirm_payload = app.stripe_confirm(
            stripe,
            cs_id,
            pm_id,
            stripe_pk_checkout,
            "paypal",
            init_payload,
            ctx,
            checkout,
            req,
            hosted,
        )
        print("confirm OK keys", sorted(confirm_payload.keys())[:12])
        redirect = app.extract_redirect_to_url(confirm_payload)
        print("redirect", redirect[:120] if redirect else "(none)")
    except Exception as exc:
        print("confirm FAIL", exc)


if __name__ == "__main__":
    main()