"""对比 8788/8789 端口的 approve 阶梯行为（不写 session 到日志）。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

CHECKOUT = "http://bj2m1188418-region-JP:nanno2@127.0.0.1:3010"


def proxy_region(base: str, region: str) -> str:
    return re.sub(r"region-[A-Za-z]{2}", f"region-{region}", base, flags=re.I)


def run_port(port: int, session: str) -> dict:
    api = f"http://127.0.0.1:{port}/api/long-link/stream"
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
    error_msg = ""
    try:
        with requests.post(api, json=payload, stream=True, timeout=180) as resp:
            if resp.status_code != 200:
                return {"port": port, "http": resp.status_code, "body": resp.text[:500]}
            for raw in resp.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                event = json.loads(raw)
                if event.get("step") == "chatgpt_approve":
                    approve_events.append(
                        {
                            "message": (event.get("message") or "")[:120],
                            "approve_result": (event.get("data") or {}).get("approve_result"),
                            "pool_size": (event.get("data") or {}).get("approve_pool_size"),
                            "tier": (event.get("data") or {}).get("approve_escalation_tier"),
                            "attempt": (event.get("data") or {}).get("approve_attempt"),
                        }
                    )
                if event.get("type") == "result":
                    result_data = event.get("data") or {}
                if event.get("type") == "error":
                    error_msg = str(event.get("message") or "")
                    break
    except Exception as exc:
        return {"port": port, "error": str(exc)}

    approved_idx = next(
        (i for i, e in enumerate(approve_events) if e.get("approve_result") == "approved"),
        None,
    )
    exception_after = False
    if approved_idx is not None:
        for e in approve_events[approved_idx + 1 : approved_idx + 8]:
            if e.get("approve_result") == "exception":
                exception_after = True
                break

    escalation = any("阶梯" in (e.get("message") or "") or e.get("tier") for e in approve_events)
    serial_skip = any("跳过后续重复 approve" in (e.get("message") or "") for e in approve_events)

    return {
        "port": port,
        "escalation_mode": escalation,
        "serial_approved_skip": serial_skip,
        "approve_event_count": len(approve_events),
        "first_events": approve_events[:8],
        "approved_idx": approved_idx,
        "exception_after_approved": exception_after,
        "result": {
            "ok": (result_data or {}).get("ok"),
            "approve_result": (result_data or {}).get("approve_result"),
            "pm": str((result_data or {}).get("pm_redirect_url") or "")[:100],
        },
        "error": error_msg,
    }


def main() -> int:
    session_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("_session_kk.json")
    session = session_path.read_text(encoding="utf-8").strip()
    ports = [int(p) for p in (sys.argv[2:] if len(sys.argv) > 2 else ["8788", "8789"])]
    for port in ports:
        print(f"\n===== port {port} =====")
        print(json.dumps(run_port(port, session), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())