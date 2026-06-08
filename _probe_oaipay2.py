import re
import requests

r = requests.get("https://oaipay.12001234.xyz/", timeout=30).text
# extract key defaults from HTML/JS
for label in ["billingCountry", "paymentLocale", "linkType", "maxRetries", "approve", "proxy", "DE", "selected", "default"]:
    idx = 0
    while True:
        i = r.find(label, idx)
        if i < 0:
            break
        print(label, "->", repr(r[max(0, i - 40) : i + 120]))
        idx = i + len(label)
        if idx - i > 5000:
            break

# find fetch payload keys
for m in re.finditer(r"fetch\([\"']([^\"']+)[\"']", r):
    print("fetch", m.group(1))