"""解析 payurl.ark2.cn HAR，提取关键 API 流程。"""
from __future__ import annotations

import json
import re
import sys
from urllib.parse import urlparse

HAR = r"D:\Edge-Download\payurl.ark2.cn.har"

KEY_HOSTS = (
    "chatgpt.com",
    "api.stripe.com",
    "paypal.com",
    "pm-redirects.stripe.com",
    "pay.openai.com",
    "checkout.stripe.com",
    "ark2.cn",
    "payurl",
)


def short_body(text: str, limit: int = 400) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:limit]


def main() -> int:
    with open(HAR, encoding="utf-8") as f:
        har = json.load(f)
    entries = har.get("log", {}).get("entries", [])
    print(f"total_entries={len(entries)}")
    idx = 0
    for e in entries:
        req = e.get("request", {})
        res = e.get("response", {})
        url = req.get("url", "")
        parsed = urlparse(url)
        host = parsed.netloc
        path = parsed.path
        if not any(k in url for k in KEY_HOSTS):
            continue
        method = req.get("method", "")
        status = res.get("status", 0)
        started = e.get("startedDateTime", "")
        time_ms = e.get("time", 0)
        idx += 1
        print(f"\n--- #{idx} {method} {status} {time_ms:.0f}ms ---")
        print(f"URL: {url[:220]}")
        hdrs = {h["name"].lower(): h["value"] for h in req.get("headers", []) if "name" in h}
        for k in ("user-agent", "referer", "authorization", "content-type", "oai-device-id", "oai-language"):
            if k in hdrs:
                v = hdrs[k]
                if k == "authorization" and len(v) > 40:
                    v = v[:20] + "..." + v[-8:]
                print(f"  {k}: {v[:180]}")
        post = req.get("postData", {}) or {}
        if post.get("text"):
            body = post["text"]
            print(f"  body: {short_body(body, 500)}")
        content = res.get("content", {}) or {}
        text = content.get("text", "") or ""
        if text:
            if "ba_token" in text or "checkout_session" in text or "requires_approval" in text or "redirect" in text:
                print(f"  resp: {short_body(text, 800)}")
            elif "paypal.com" in text:
                print(f"  resp(paypal): {short_body(text, 300)}")
        if "ba_token=" in url:
            print(f"  ** BA in URL **")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())