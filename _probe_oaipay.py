import re
import requests

base = "https://oaipay.12001234.xyz"
r = requests.get(base + "/", timeout=30)
print("status", r.status_code, "len", len(r.text))
for pat in [r"/api/[a-zA-Z0-9_/-]+", r"billing_country", r"paymentStrategy", r"approvePool", r"DE", r"de-DE", r"Europe/Berlin"]:
    hits = sorted(set(re.findall(pat, r.text)))
    if hits:
        print(pat, hits[:20])
# inline script snippets
for m in re.finditer(r"<script[^>]*>([\s\S]{0,8000}?)</script>", r.text):
    chunk = m.group(1)
    if "billing" in chunk or "long-link" in chunk or "DE" in chunk:
        print("--- script chunk ---")
        print(chunk[:3000])