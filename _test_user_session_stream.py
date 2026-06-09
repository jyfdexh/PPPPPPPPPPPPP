"""解析 stream 日志，检查 approve 阶梯与 approved/exception 行为。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

API = "http://127.0.0.1:8788/api/long-link/stream"
CHECKOUT = "http://bj2m1188418-region-JP:nanno2@127.0.0.1:3010"


def proxy_region(base: str, region: str) -> str:
    import re

    return re.sub(r"region-[A-Za-z]{2}", f"region-{region}", base, flags=re.I)


def main() -> int:
    session_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("测试session/user_session.json")
    session = session_path.read_text(encoding="utf-8").strip()
    payload = {
        "accessToken": session,
        "link_type": "paypal",
        "billing_country": "DE",
        "paymentStrategy": "jp_de",
        "fetchBaToken": False,
        "proxy": proxy_region(CHECKOUT, "JP"),
        "checkoutProxy": proxy_region(CHECKOUT, "JP"),
        "providerProxy": proxy_region(CHECKOUT, "DE"),
        "approveProxy": proxy_region(CHECKOUT, "JP"),
        "maxRetries": 1,
        "approvePoolMaxAttempts": 50,
    }
    approve_events: list[dict] = []
    result_data: dict | None = None
    with requests.post(API, json=payload, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            event = json.loads(raw)
            if event.get("step") == "chatgpt_approve":
                approve_events.append(
                    {
                        "message": event.get("message"),
                        "approve_result": (event.get("data") or {}).get("approve_result"),
                        "pool_size": (event.get("data") or {}).get("approve_pool_size"),
                        "tier": (event.get("data") or {}).get("approve_escalation_tier"),
                        "attempt": (event.get("data") or {}).get("approve_attempt"),
                    }
                )
            if event.get("type") == "result":
                result_data = event.get("data") or {}
            if event.get("type") == "error":
                print("ERROR:", event.get("message"))
                break

    print("--- approve 事件摘要 ---")
    for item in approve_events[:30]:
        print(item)
    if len(approve_events) > 30:
        print(f"... 共 {len(approve_events)} 条")
    print("--- 结果 ---")
    print(
        json.dumps(
            {
                "ok": (result_data or {}).get("ok"),
                "approve_result": (result_data or {}).get("approve_result"),
                "pm": str((result_data or {}).get("pm_redirect_url") or "")[:120],
                "long_url": str((result_data or {}).get("long_url") or "")[:120],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    approved_idx = next((i for i, e in enumerate(approve_events) if e.get("approve_result") == "approved"), None)
    exception_after = False
    if approved_idx is not None:
        for e in approve_events[approved_idx + 1 : approved_idx + 6]:
            if e.get("approve_result") == "exception":
                exception_after = True
                break
    print("approved 后 5 条内出现 exception 日志:", exception_after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())