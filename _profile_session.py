"""全链路耗时剖析：按 step 统计间隔与总时长。"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

API = "http://127.0.0.1:8788/api/long-link/stream"
CHECKOUT = "http://bj2m1188418-region-JP:nanno2@127.0.0.1:3010"


def proxy_region(base: str, region: str) -> str:
    return re.sub(r"region-[A-Za-z]{2}", f"region-{region}", base, flags=re.I)


def run_once(session: str) -> dict:
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
    t0 = time.perf_counter()
    events: list[dict] = []
    result_data: dict | None = None
    error_msg = ""
    with requests.post(API, json=payload, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            event = json.loads(raw)
            now = time.perf_counter()
            events.append(
                {
                    "t": now - t0,
                    "type": event.get("type") or event.get("event"),
                    "step": event.get("step") or "",
                    "message": (event.get("message") or "")[:100],
                    "data": event.get("data") or {},
                }
            )
            if event.get("type") == "result":
                result_data = event.get("data") or {}
            if event.get("type") == "error":
                error_msg = str(event.get("message") or "")
                break
    total = time.perf_counter() - t0
    return {
        "total_s": round(total, 2),
        "events": events,
        "result": result_data,
        "error": error_msg,
    }


def summarize(run: dict) -> dict:
    events = run["events"]
    step_first: dict[str, float] = {}
    step_last: dict[str, float] = {}
    gaps: list[dict] = []
    prev_t = 0.0
    prev_step = ""
    for ev in events:
        step = ev["step"] or ev["type"] or "unknown"
        t = ev["t"]
        if step not in step_first:
            step_first[step] = t
        step_last[step] = t
        gap = t - prev_t
        if gap >= 1.0:
            gaps.append({"gap_s": round(gap, 2), "after": prev_step, "before": step, "msg": ev["message"]})
        prev_t = t
        prev_step = step

    step_durations = {
        step: round(step_last[step] - step_first[step], 2)
        for step in step_first
        if step_last[step] - step_first[step] >= 0.3
    }
    approve_events = [e for e in events if e["step"] == "chatgpt_approve"]
    return {
        "total_s": run["total_s"],
        "ok": (run.get("result") or {}).get("ok"),
        "approve_result": (run.get("result") or {}).get("approve_result"),
        "pm_hit": bool((run.get("result") or {}).get("pm_redirect_url")),
        "error": run.get("error") or "",
        "step_durations_s": dict(sorted(step_durations.items(), key=lambda x: -x[1])),
        "gaps_over_1s": gaps[:15],
        "approve_count": len(approve_events),
        "approve_timeline": [
            {
                "t": round(e["t"], 2),
                "msg": e["message"],
                "tier": e["data"].get("approve_escalation_tier"),
                "result": e["data"].get("approve_result"),
            }
            for e in approve_events
        ],
    }


def main() -> int:
    session_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("_session_kk.json")
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    session = session_path.read_text(encoding="utf-8").strip()
    summaries = []
    for i in range(runs):
        print(f"=== run {i + 1}/{runs} ===", flush=True)
        run = run_once(session)
        summaries.append(summarize(run))
        print(json.dumps(summaries[-1], ensure_ascii=False, indent=2), flush=True)
        if i + 1 < runs:
            time.sleep(2)
    totals = [s["total_s"] for s in summaries]
    print("\n=== 汇总 ===")
    print(json.dumps({"runs": len(summaries), "total_s": totals, "avg_s": round(sum(totals) / len(totals), 2)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())