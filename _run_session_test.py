"""单次/多次全链路测试：默认全程无代理 + approve 6 次。"""
from __future__ import annotations

import json
import sys
import time

import requests

BASE = "http://127.0.0.1:8787/api/long-link/stream"


def run_once() -> dict:
    payload = {
        "accessToken": __import__("_test_terminate").TOKEN,
        "link_type": "paypal",
        "billing_country": "DE",
        "payment_locale": "de",
        "paymentStrategy": "jp_de",
        "allNoProxy": True,
        "approveAttemptCount": 6,
        "maxRetries": 1,
        "fetchBaToken": False,
    }
    t0 = time.perf_counter()
    events: list[dict] = []
    result: dict | None = None
    error = ""
    with requests.post(BASE, json=payload, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            ev = json.loads(raw)
            now = time.perf_counter() - t0
            step = ev.get("step") or ev.get("type") or ""
            events.append(
                {
                    "t": round(now, 2),
                    "step": step,
                    "message": (ev.get("message") or "")[:120],
                    "data": ev.get("data") or {},
                }
            )
            print(f"[{now:6.1f}s] {step}: {(ev.get('message') or '')[:90]}")
            if ev.get("type") == "result":
                result = ev.get("data") or {}
            if ev.get("type") == "error":
                error = str(ev.get("message") or "")
                break
            if ev.get("type") == "cancelled":
                error = str(ev.get("message") or "cancelled")
                break
    total = round(time.perf_counter() - t0, 2)
    gaps = []
    prev = 0.0
    prev_step = ""
    for e in events:
        gap = e["t"] - prev
        if gap >= 1.0:
            gaps.append({"gap_s": round(gap, 2), "from": prev_step, "to": e["step"], "msg": e["message"]})
        prev = e["t"]
        prev_step = e["step"]
    approve = [e for e in events if e["step"] == "chatgpt_approve"]
    summary = {
        "total_s": total,
        "ok": (result or {}).get("ok"),
        "approve_result": (result or {}).get("approve_result"),
        "pm_redirect_url": (result or {}).get("pm_redirect_url", "")[:80],
        "long_url": (result or {}).get("long_url", "")[:80],
        "error": error,
        "approve_events": len(approve),
        "approve_timeline": [
            {
                "t": e["t"],
                "tier": e["data"].get("approve_escalation_tier"),
                "pool": e["data"].get("approve_pool_size"),
                "result": e["data"].get("approve_result"),
                "msg": e["message"][:80],
            }
            for e in approve
        ],
        "gaps_over_1s": gaps,
    }
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    runs = max(1, int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    totals = []
    for i in range(runs):
        if i:
            print(f"\n--- run {i + 1}/{runs} ---\n")
            time.sleep(1.5)
        totals.append(run_once()["total_s"])
    if runs > 1:
        print(f"\navg={sum(totals)/len(totals):.2f}s totals={totals}")