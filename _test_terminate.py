"""Test stream + terminate flow."""
from __future__ import annotations

import json
import threading
import time
import uuid

import requests

BASE = "http://127.0.0.1:8787"
TOKEN = (
    "eyJhbGciOiJSUzI1NiIsImtpZCI6IjE5MzQ0ZTY1LWJiYzktNDRkMS1hOWQwLWY5NTdiMDc5YmQwZSIsInR5cCI6IkpXVCJ9."
    "eyJhdWQiOlsiaHR0cHM6Ly9hcGkub3BlbmFpLmNvbS92MSJdLCJjbGllbnRfaWQiOiJhcHBfWDh6WTZ2VzJwUTl0UjNkRTduSzFqTDVnSCIsImV4cCI6MTc4MTc2ODgwNywiaHR0cHM6Ly9hcGkub3BlbmFpLmNvbS9hdXRoIjp7ImNoYXRncHRfYWNjb3VudF9pZCI6ImU4NTkyNjY2LWJjZWYtNGU5NS1iNjZhLWRjOWM4NzRhNjU2ZiIsImNoYXRncHRfYWNjb3VudF91c2VyX2lkIjoidXNlci00ZzFFZDBZcTNQVzhnN0wxNkZsQm1SYVFfX2U4NTkyNjY2LWJjZWYtNGU5NS1iNjZhLWRjOWM4NzRhNjU2ZiIsImNoYXRncHRfY29tcHV0ZV9yZXNpZGVuY3kiOiJub19jb25zdHJhaW50IiwiY2hhdGdwdF9wbGFuX3R5cGUiOiJmcmVlIiwiY2hhdGdwdF91c2VyX2lkIjoidXNlci00ZzFFZDBZcTNQVzhnN0wxNkZsQm1SYVEiLCJpc19zaWdudXAiOnRydWUsInVzZXJfaWQiOiJ1c2VyLTRnMUVkMFlxM1BXOGc3TDE2RmxCbVJhUSJ9LCJodHRwczovL2FwaS5vcGVuYWkuY29tL3Byb2ZpbGUiOnsiZW1haWwiOiJUcmFwYW5pUHVlcnRvNDFAb3V0bG9vay5jb20iLCJlbWFpbF92ZXJpZmllZCI6dHJ1ZX0sImlhdCI6MTc4MDkwNDgwNywiaXNzIjoiaHR0cHM6Ly9hdXRoLm9wZW5haS5jb20iLCJqdGkiOiI5NGIxZWEwYS1lOTIwLTRjNmQtODliZC02OGYzOGIxZTU5ZTgiLCJuYmYiOjE3ODA5MDQ4MDcsInB3ZF9hdXRoX3RpbWUiOjE3ODA5MDQ4MDQ3NjgsInNjcCI6WyJvcGVuaWQiLCJlbWFpbCIsInByb2ZpbGUiLCJvZmZsaW5lX2FjY2VzcyIsIm1vZGVsLnJlcXVlc3QiLCJtb2RlbC5yZWFkIiwib3JnYW5pemF0aW9uLnJlYWQiLCJvcmdhbml6YXRpb24ud3JpdGUiXSwic2Vzc2lvbl9pZCI6ImF1dGhzZXNzX1l0S2JzUFR3aGF2R0FjaThTYkpHSkpBbiIsInNsIjp0cnVlLCJzdWIiOiJhdXRoMHxZYjd5cGpnZDJmSDV4dFBrZEVWa00zRVYifQ."
    "FsDTGpUndGmW1nEYTHGL1hgphXJisOwrn6LX0d3L5XuPSfBeKIJWxj2QImHOKcpOH4FNlWvmKVoXT3uKTdT8-WmaC9kwagO5VPl810noXEn5eQsfbKj_oxtFXHhkp0SLtU_nKtNxxeS1YjpVpWExhj7lU84d__am4SSm-VCmlzR9Acfai0MXinumpUdSkgapPtpQm-flR_BSca2xZtii3TrQrHkRSurBUbGgKP-av2EAd6nGywUaKjehUAvnl6awh50MpnI9CUKqtR0FtPy5yXslnj0ur3wn5ZXDqkdwYxfh2ntb7o5Q5MTL4G99kj13_RMMJK-8dk98zV5zLVKuEh-AdX3MpA8mGohGOhm1gP3ri4eGX_YZKcx6v4vJuzKrrgh1ntYyYsry4HGZ7uOfn46Yc5v5DNXtFW1XSa2RXRgk81-tzbYiguyG-ErZNMDesYBOTPSKnmenk0-d0xxJHLXFHyM8n3NKPWot4JSifSZVNuwR7TaAK5X1uzt2Hcy3v76LIzxgoH0LoMGQTlG4totHRqJdEUpDb_G6vG0_72brCGCr3JAWT7cSgYiGC53KQHzUcMP9ERPrBam6ARACC0uvRVY686DBoxngMmS-_Y1tzhHRnITQ-bttYJeGusEuymXh-d5ISF654qRfobJxRlZ0_rtcBS72q3OyaZXDR6U"
)


def probe_routes(task_id: str) -> None:
    for port in (8787, 8788):
        url = f"http://127.0.0.1:{port}/api/long-link/tasks/{task_id}/terminate"
        try:
            resp = requests.post(url, timeout=5)
            print(f"[probe:{port}] {resp.status_code} {resp.text[:200]}")
        except Exception as exc:
            print(f"[probe:{port}] error: {exc}")


def test_empty_task_id_404() -> None:
    resp = requests.post(f"{BASE}/api/long-link/tasks//terminate", timeout=5)
    print(f"[empty-task-id] status={resp.status_code} body={resp.text[:120]}")


def run_stream_terminate() -> None:
    task_id = str(uuid.uuid4())
    payload = {
        "accessToken": TOKEN,
        "link_type": "paypal",
        "billing_country": "DE",
        "payment_locale": "de",
        "paymentStrategy": "jp_de",
        "allNoProxy": True,
        "approveAttemptCount": 6,
        "taskId": task_id,
    }
    print(f"task_id={task_id}")

    events: list[dict] = []
    done = threading.Event()

    def reader() -> None:
        with requests.post(
            f"{BASE}/api/long-link/stream",
            json=payload,
            stream=True,
            timeout=120,
        ) as resp:
            print(f"[stream] status={resp.status_code}")
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                item = json.loads(line)
                events.append(item)
                step = item.get("step") or item.get("type")
                print(f"[stream] {step}: {str(item.get('message') or '')[:80]}")
                if item.get("type") in {"result", "error", "cancelled"}:
                    break
        done.set()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    time.sleep(2.5)

    term_url = f"{BASE}/api/long-link/tasks/{task_id}/terminate"
    term = requests.post(term_url, timeout=10)
    print(f"[terminate] url={term_url}")
    print(f"[terminate] status={term.status_code} body={term.text[:300]}")

    done.wait(timeout=30)
    types = [e.get("type") for e in events]
    print(f"[summary] event_types={types[-8:]}")


if __name__ == "__main__":
    task_id = "da5a57c0-5537-4e70-bc13-f870b6ae39ea"
    test_empty_task_id_404()
    probe_routes(task_id)
    run_stream_terminate()