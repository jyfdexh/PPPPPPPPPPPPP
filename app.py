from __future__ import annotations

import json
import os
import queue
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import uuid
from html import unescape as html_unescape
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

try:
    from curl_cffi.requests import Session as CurlCffiSession  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    CurlCffiSession = None  # type: ignore


DEFAULT_STRIPE_PK = (
    "pk_live_51HOrSwC6h1nxGoI3lTAgRjYVrz4dU3fVOabyCcKR3pbEJguCVAlqCxdxCUvoRh1XWwRac"
    "ViovU3kLKvpkjh7IqkW00iXQsjo3n"
)
STRIPE_VERSION_FULL = "2025-03-31.basil; checkout_server_update_beta=v1; checkout_manual_approval_preview=v1"
DEFAULT_TIMEOUT = 30
BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
DEFAULT_PROXY = os.getenv(
    "OPENAI_PAY_DEFAULT_PROXY",
    "http://bj2m1188418-region-JP:nanno2@127.0.0.1:3010",
).strip()
PROVIDER_STAGE_PROXY = os.getenv("OPENAI_PAY_PROVIDER_PROXY", "").strip()
GOPAY_PROVIDER_STAGE_PROXY = os.getenv(
    "OPENAI_PAY_GOPAY_PROVIDER_PROXY",
    "http://dsgytrca-region-ID-sid--t-5:udhhdhdhsjadsa@us2.cliproxy.io:3010",
).strip()
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)
DEFAULT_STRIPE_RUNTIME_VERSION = "6f8494a281"
US_BILLING_NAMES = [
    ("James", "Smith"),
    ("John", "Brown"),
    ("Michael", "Johnson"),
    ("Robert", "Miller"),
    ("David", "Davis"),
    ("William", "Wilson"),
]
US_BILLING_STREETS = [
    ("3110 Sunset Boulevard", "Los Angeles", "CA", "90026"),
    ("1200 Market Street", "San Francisco", "CA", "94102"),
    ("500 Main Street", "Austin", "TX", "78701"),
    ("88 Broadway", "New York", "NY", "10007"),
    ("1200 Peachtree St", "Atlanta", "GA", "30309"),
]
DE_BILLING_NAMES = [
    ("Lukas", "Müller"),
    ("Anna", "Schmidt"),
    ("Felix", "Weber"),
    ("Sophie", "Fischer"),
    ("Jonas", "Becker"),
]
DE_BILLING_STREETS = [
    ("Friedrichstraße 123", "Berlin", "Berlin", "10117"),
    ("Marienplatz 8", "München", "Bayern", "80331"),
    ("Zeil 85", "Frankfurt", "Hessen", "60313"),
    ("Neuer Wall 50", "Hamburg", "Hamburg", "20354"),
    ("Königsallee 60", "Düsseldorf", "Nordrhein-Westfalen", "40212"),
]
JAPAN_BILLING_NAMES = [
    ("Taro", "Yamada"),
    ("Hanako", "Sato"),
    ("Ken", "Suzuki"),
    ("Yui", "Takahashi"),
    ("Haruto", "Tanaka"),
]
JAPAN_BILLING_STREETS = [
    ("1-2-3 Shibuya", "Shibuya-ku", "Tokyo", "150-0002"),
    ("2-1-1 Namba", "Chuo-ku", "Osaka", "542-0076"),
    ("3-4-5 Sakae", "Naka-ku", "Aichi", "460-0008"),
    ("4-2-8 Hakata", "Hakata-ku", "Fukuoka", "812-0011"),
]
INDONESIA_BILLING_NAMES = [
    ("Budi", "Santoso"),
    ("Agus", "Wijaya"),
    ("Siti", "Rahma"),
    ("Dewi", "Lestari"),
    ("Rizky", "Pratama"),
]
INDONESIA_BILLING_STREETS = [
    ("Jl. Jend. Sudirman No. 1", "Jakarta", "DKI Jakarta", "10210"),
    ("Jl. MH Thamrin No. 10", "Jakarta", "DKI Jakarta", "10350"),
    ("Jl. Asia Afrika No. 8", "Bandung", "Jawa Barat", "40111"),
    ("Jl. Basuki Rahmat No. 5", "Surabaya", "Jawa Timur", "60271"),
]
COUNTRY_CURRENCY = {
    "AT": "EUR",
    "AU": "AUD",
    "BE": "EUR",
    "BR": "BRL",
    "CA": "CAD",
    "CH": "CHF",
    "CZ": "CZK",
    "DE": "EUR",
    "DK": "DKK",
    "ES": "EUR",
    "FI": "EUR",
    "FR": "EUR",
    "GB": "GBP",
    "HK": "HKD",
    "ID": "IDR",
    "IE": "EUR",
    "IN": "INR",
    "IT": "EUR",
    "JP": "JPY",
    "KR": "KRW",
    "MX": "MXN",
    "MY": "MYR",
    "NL": "EUR",
    "NO": "NOK",
    "NZ": "NZD",
    "PH": "PHP",
    "PL": "PLN",
    "PT": "EUR",
    "SE": "SEK",
    "SG": "SGD",
    "TH": "THB",
    "TW": "TWD",
    "US": "USD",
    "VN": "VND",
}
PAYMENT_STRATEGY_PROFILES: dict[str, dict[str, str]] = {
    "jp_us": {
        "billing_country": "US",
        "payment_locale": "en",
        "checkout_region": "JP",
        "provider_region": "US",
        "stripe_timezone": "Asia/Shanghai",
        "accept_language": "en-US,en;q=0.9",
    },
    "de_eur": {
        "billing_country": "DE",
        "payment_locale": "de",
        "checkout_region": "DE",
        "provider_region": "DE",
        "stripe_timezone": "Europe/Berlin",
        "accept_language": "de-DE,de;q=0.9,en;q=0.8",
    },
    "de_billing_us_provider": {
        "billing_country": "DE",
        "payment_locale": "de",
        "checkout_region": "DE",
        "provider_region": "US",
        "stripe_timezone": "Europe/Berlin",
        "accept_language": "de-DE,de;q=0.9,en;q=0.8",
    },
    "jp_de_billing": {
        "billing_country": "DE",
        "payment_locale": "de",
        "checkout_region": "JP",
        "provider_region": "DE",
        "stripe_timezone": "Europe/Berlin",
        "accept_language": "de-DE,de;q=0.9,en;q=0.8",
    },
}
LOCALE_MAP = {
    "de": ("de-DE", "de"),
    "en": ("en-US", "en"),
    "en-US": ("en-US", "en"),
    "es": ("es-ES", "es"),
    "fr": ("fr-FR", "fr"),
    "id": ("id-ID", "id"),
    "it": ("it-IT", "it"),
    "ja": ("ja-JP", "ja"),
    "ko": ("ko-KR", "ko"),
    "pt-BR": ("pt-BR", "pt-BR"),
    "zh-CN": ("zh-CN", "zh-CN"),
    "zh-TW": ("zh-TW", "zh-TW"),
}


class LongLinkRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    access_token: str = Field(..., alias="accessToken")
    proxy: str = ""
    checkout_proxy: str = Field("", alias="checkoutProxy")
    provider_proxy: str = Field("", alias="providerProxy")
    stripe_publishable_key: str = ""
    billing_country: str = "US"
    checkout_ui_mode: str = "hosted"
    payment_locale: str = "en"
    link_type: str = "hosted"
    device_id: str = ""
    user_agent: str = ""
    max_retries: int = Field(5, alias="maxRetries")
    approve_retries: int = Field(10, alias="approveRetries")
    approve_pool_size: int = Field(30, alias="approvePoolSize")
    approve_pool_max_attempts: int = Field(600, alias="approvePoolMaxAttempts")
    payment_strategy: str = Field("de_eur", alias="paymentStrategy")
    stripe_timezone: str = Field("", alias="stripeTimezone")
    task_id: str = Field("", alias="taskId")


class RetryHistoryItem(BaseModel):
    attempt: int
    ok: bool
    error: str = ""
    fallback: bool = False
    long_url: str = ""


class LongLinkResponse(BaseModel):
    ok: bool
    cs_id: str
    processor_entity: str
    billing_country: str
    currency: str
    payment_locale: str
    link_type: str
    payment_method_type: str
    payment_method_id: str
    stripe_redirect_url: str
    provider_redirect_url: str
    fallback: bool = False
    provider_error: str = ""
    stripe_hosted_url: str
    long_url: str
    approve_result: str = ""
    attempt_count: int = 1
    max_attempts: int = 1
    retry_history: list[RetryHistoryItem] = Field(default_factory=list)


class PublicPayPalLinkRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    access_token: str = Field("", alias="accessToken")
    session_json: str = Field("", alias="sessionJson")
    proxy: str = ""
    checkout_proxy: str = Field("", alias="checkoutProxy")
    provider_proxy: str = Field("", alias="providerProxy")
    max_retries: int = Field(5, alias="maxRetries")
    approve_retries: int = Field(10, alias="approveRetries")


class PublicPayPalLinkResponse(BaseModel):
    success: bool
    code: str
    message: str
    paypal_link: str
    hosted_long_url: str
    attempt_count: int
    max_attempts: int
    retries_used: int
    cs_id: str
    billing_country: str
    currency: str
    provider_error: str
    last_error: str
    provider_redirect_url: str
    stripe_redirect_url: str
    stripe_hosted_url: str
    retry_history: list[RetryHistoryItem] = Field(default_factory=list)


class ProxyCheckRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    proxy_input: str = Field("", alias="proxyInput")
    proxy: str = ""
    checkout_proxy: str = Field("", alias="checkoutProxy")
    provider_proxy: str = Field("", alias="providerProxy")
    link_type: str = Field("hosted", alias="linkType")
    stage: str = ""


class ProxyCheckItem(BaseModel):
    stage: str
    label: str
    ok: bool
    proxy_hint: str
    protocol: str
    selection_kind: str = ""
    selection_source: str = ""
    ip: str = ""
    country: str = ""
    country_code: str = ""
    region: str = ""
    city: str = ""
    isp: str = ""
    org: str = ""
    source: str = ""
    error: str = ""


class ProxyCheckResponse(BaseModel):
    ok: bool
    message: str
    checks: list[ProxyCheckItem] = Field(default_factory=list)


ProgressLogger = Callable[[str, str, dict[str, Any] | None], None]


def noop_progress(_step: str, _message: str, _data: dict[str, Any] | None = None) -> None:
    return None


def new_session() -> Any:
    if CurlCffiSession is not None:
        verify: bool | str = False
        if os.name != "nt":
            try:
                import certifi

                ca_path = certifi.where()
                if ca_path and Path(ca_path).is_file() and ca_path.isascii():
                    verify = ca_path
            except Exception:
                verify = False
        try:
            return CurlCffiSession(impersonate="chrome136", verify=verify)
        except Exception:
            try:
                return CurlCffiSession(impersonate="chrome136", verify=False)
            except Exception:
                pass
    return requests.Session()


def effective_default_proxy(proxy: str = "") -> str:
    return normalize_proxy_url(str(proxy or "").strip() or DEFAULT_PROXY)


def build_http_proxy_url(host: str, port: str, username: str, password: str) -> str:
    host = str(host or "").strip()
    port = str(port or "").strip()
    username = str(username or "").strip()
    password = str(password or "").strip()
    if not host or not port or not username or not password:
        raise RuntimeError("invalid proxy format: host/port/username/password required")
    return f"http://{quote(username, safe='')}:{quote(password, safe='')}@{host}:{port}"


def normalize_proxy_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" in raw:
        parsed = urlsplit(raw)
        if parsed.scheme.lower() in {"http", "https", "socks5", "socks5h"} and parsed.hostname and parsed.port:
            return raw
        raise RuntimeError("invalid proxy format")
    if "@" in raw:
        left, right = raw.split("@", 1)
        if ":" in left and ":" in right:
            if right.count(":") == 1:
                username, password = left.split(":", 1)
                host, port = right.split(":", 1)
                return build_http_proxy_url(host, port, username, password)
            if left.count(":") == 1:
                host, port = left.split(":", 1)
                username, password = right.split(":", 1)
                return build_http_proxy_url(host, port, username, password)
    parts = raw.split(":")
    if len(parts) == 4 and parts[1].isdigit():
        host, port, username, password = parts
        return build_http_proxy_url(host, port, username, password)
    if len(parts) == 2 and parts[1].isdigit():
        host, port = parts
        return f"http://{host.strip()}:{port.strip()}"
    raise RuntimeError("invalid proxy format")


def mask_proxy_url(proxy_url: str) -> str:
    parsed = urlsplit(str(proxy_url or ""))
    if parsed.username or parsed.password:
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://***:***@{host}{port}"
    return str(proxy_url or "")


def safe_proxy_hint(proxy_url: str) -> str:
    if not proxy_url:
        return ""
    parsed = urlsplit(str(proxy_url or ""))
    if parsed.hostname:
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{parsed.hostname}{port}"
    return mask_proxy_url(proxy_url)


def proxy_candidates(proxy_url: str) -> list[str]:
    proxy_url = str(proxy_url or "").strip()
    if not proxy_url:
        return [""]
    candidates: list[str] = []
    parsed = urlsplit(proxy_url)
    if parsed.scheme.lower() in {"socks5", "socks5h"} and parsed.hostname and parsed.port:
        username = parsed.username or ""
        password = parsed.password or ""
        if username and password:
            candidates.append(build_http_proxy_url(parsed.hostname, str(parsed.port), username, password))
    candidates.append(proxy_url)
    return list(dict.fromkeys(candidates))


def proxy_runtime_url(session: Any, proxy: str = "") -> str:
    proxies = getattr(session, "proxies", None)
    if isinstance(proxies, dict):
        for key in ("https", "http"):
            value = str(proxies.get(key) or "").strip()
            if value:
                return value
    proxy = normalize_proxy_url(proxy) if proxy else ""
    if not proxy:
        return ""
    if CurlCffiSession is not None and isinstance(session, CurlCffiSession):
        return proxy_candidates(proxy)[0]
    return proxy


def proxy_runtime_details(session: Any, proxy: str = "") -> dict[str, str]:
    runtime_proxy = proxy_runtime_url(session, proxy)
    session_impl = "curl_cffi" if CurlCffiSession is not None and isinstance(session, CurlCffiSession) else "requests"
    if not runtime_proxy:
        return {"actual_proxy": "direct", "actual_protocol": "direct", "session_impl": session_impl}
    parsed = urlsplit(runtime_proxy)
    return {
        "actual_proxy": safe_proxy_hint(runtime_proxy),
        "actual_protocol": str(parsed.scheme or "unknown"),
        "session_impl": session_impl,
    }


def set_proxy_url(session: Any, proxy: str) -> None:
    resolved_proxy = proxy_runtime_url(session, proxy)
    session.proxies = {"http": resolved_proxy, "https": resolved_proxy} if resolved_proxy else {}


def set_proxy(session: Any, proxy: str) -> None:
    set_proxy_url(session, effective_default_proxy(proxy))


def proxy_for_region(proxy: str, region: str) -> str:
    proxy = normalize_proxy_url(proxy)
    region = str(region or "").strip().upper()
    if proxy and region and "region-" in proxy:
        return re.sub(r"region-[A-Za-z]{2}", f"region-{region}", proxy)
    return proxy


def checkout_stage_proxy(req: Any) -> str:
    return effective_default_proxy(
        getattr(req, "checkout_proxy", "")
        or getattr(req, "proxy_input", "")
        or getattr(req, "proxy", "")
        or DEFAULT_PROXY
    )


def provider_stage_proxy(req: Any) -> str:
    explicit = str(getattr(req, "provider_proxy", "") or "").strip()
    if explicit:
        return normalize_proxy_url(explicit)
    link_type = normalize_link_type(getattr(req, "link_type", ""))
    if link_type == "gopay":
        return GOPAY_PROVIDER_STAGE_PROXY or proxy_for_region(DEFAULT_PROXY, "ID")
    if PROVIDER_STAGE_PROXY:
        return PROVIDER_STAGE_PROXY
    base_proxy = checkout_stage_proxy(req)
    region_base = base_proxy if "region-" in base_proxy else DEFAULT_PROXY
    if link_type == "paypal":
        billing_country = normalize_country(getattr(req, "billing_country", None) or "US")
        provider_region = billing_country if billing_country in COUNTRY_CURRENCY else "US"
        return proxy_for_region(region_base, provider_region)
    return proxy_for_region(region_base, "US")


def apply_provider_proxy(chatgpt: Any, proxy: str) -> None:
    return None


def currency_for_country(country: str) -> str:
    return COUNTRY_CURRENCY.get(str(country or "").upper(), "USD")


def normalize_country(country: str) -> str:
    country = str(country or "").strip().upper()
    return country if country in COUNTRY_CURRENCY else "US"


def country_zh(country: str) -> str:
    mapping = {
        "DE": "德国",
        "ID": "Indonesia",
        "JP": "Japan",
        "US": "United States",
    }
    return mapping.get(str(country or "").strip().upper(), "")


def country_display(country: str, country_code: str = "") -> str:
    text = str(country or country_code or "").strip()
    zh = country_zh(country_code or country)
    if text and zh:
        return f"{text} ({zh})"
    return text or zh


def normalize_link_type(link_type: str) -> str:
    value = str(link_type or "hosted").strip().lower()
    aliases = {
        "payment": "hosted",
        "pay": "hosted",
        "long": "hosted",
        "pp": "paypal",
        "paypal": "paypal",
        "gopy": "gopay",
        "gopay": "gopay",
    }
    return aliases.get(value, "hosted")


def effective_country(req: LongLinkRequest) -> str:
    link_type = normalize_link_type(req.link_type)
    if link_type == "gopay":
        return "ID"
    if link_type == "paypal":
        return normalize_country(req.billing_country or "US")
    return normalize_country(req.billing_country)


def locale_parts(locale: str) -> tuple[str, str]:
    return LOCALE_MAP.get(str(locale or "").strip(), LOCALE_MAP["en"])


def find_token(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("accessToken", "access_token", "token"):
            token = str(value.get(key) or "").strip()
            if token:
                return token
        for item in value.values():
            token = find_token(item)
            if token:
                return token
    if isinstance(value, list):
        for item in value:
            token = find_token(item)
            if token:
                return token
    return ""


def normalize_access_token(raw: str) -> str:
    token = str(raw or "").strip()
    if not token:
        return ""
    if token.startswith("{") or token.startswith("["):
        try:
            return find_token(json.loads(token)) or token
        except json.JSONDecodeError:
            return token
    return token


def safe_token_hint(token: str) -> str:
    value = normalize_access_token(token)
    if not value:
        return ""
    return f"长度 {len(value)}，尾部 {value[-7:]}"


def normalize_max_retries(value: Any) -> int:
    try:
        parsed = int(value)
    except Exception:
        return 5
    return max(1, min(parsed, 20))


def normalize_approve_retries(value: Any) -> int:
    try:
        parsed = int(value)
    except Exception:
        return 10
    return max(1, min(parsed, 30))


def normalize_approve_pool_size(value: Any) -> int:
    try:
        parsed = int(value)
    except Exception:
        return 50
    return max(1, min(parsed, 100))


def normalize_approve_pool_max_attempts(value: Any) -> int:
    try:
        parsed = int(value)
    except Exception:
        return 3000
    return max(1, min(parsed, 5000))


def normalize_payment_strategy(value: Any) -> str:
    strategy = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "": "jp_us",
        "jp": "jp_us",
        "jp_us": "jp_us",
        "jpus": "jp_us",
        "de": "de_eur",
        "de_eur": "de_eur",
        "deeur": "de_eur",
        "de_us": "de_billing_us_provider",
        "de_billing_us_provider": "de_billing_us_provider",
        "jp_de": "jp_de_billing",
        "jp_de_billing": "jp_de_billing",
    }
    return aliases.get(strategy, strategy if strategy in PAYMENT_STRATEGY_PROFILES else "de_eur")


def stripe_timezone_for_req(req: LongLinkRequest) -> str:
    custom = str(req.stripe_timezone or "").strip()
    if custom:
        return custom
    country = effective_country(req)
    if country == "DE":
        return "Europe/Berlin"
    if country == "JP":
        return "Asia/Tokyo"
    return "Asia/Shanghai"


def strategy_proxy_base(req: LongLinkRequest) -> str:
    for candidate in (
        str(getattr(req, "checkout_proxy", "") or "").strip(),
        str(getattr(req, "provider_proxy", "") or "").strip(),
        str(getattr(req, "proxy", "") or "").strip(),
        DEFAULT_PROXY,
    ):
        if candidate:
            return candidate
    return DEFAULT_PROXY


def apply_payment_strategy(req: LongLinkRequest) -> LongLinkRequest:
    if normalize_link_type(req.link_type) != "paypal":
        return req
    strategy = normalize_payment_strategy(req.payment_strategy)
    profile = PAYMENT_STRATEGY_PROFILES.get(strategy)
    if not profile:
        return req
    region_base = strategy_proxy_base(req)
    if "region-" not in region_base:
        region_base = DEFAULT_PROXY
    updates: dict[str, Any] = {
        "billing_country": profile["billing_country"],
        "payment_locale": profile["payment_locale"],
        "stripe_timezone": profile["stripe_timezone"],
        "payment_strategy": strategy,
    }
    explicit_checkout = str(getattr(req, "checkout_proxy", "") or "").strip()
    explicit_provider = str(getattr(req, "provider_proxy", "") or "").strip()
    if not (explicit_checkout and explicit_provider):
        updates["checkout_proxy"] = proxy_for_region(region_base, profile["checkout_region"])
        updates["provider_proxy"] = proxy_for_region(region_base, profile["provider_region"])
        updates["proxy"] = proxy_for_region(region_base, profile["checkout_region"])
    return req.model_copy(update=updates)


def extract_session_email(raw_token: str) -> str:
    token = str(raw_token or "").strip()
    if not token.startswith("{"):
        return ""
    try:
        payload = json.loads(token)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    user = payload.get("user")
    if isinstance(user, dict):
        email = str(user.get("email") or "").strip()
        if email:
            return email
    return ""


def clone_http_session(session: Any) -> Any:
    cloned = new_session()
    cloned.headers.update(dict(getattr(session, "headers", {}) or {}))
    cloned.proxies = dict(getattr(session, "proxies", {}) or {})
    return cloned


def extract_processor_entity(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    direct = data.get("processor_entity") or data.get("processorEntity")
    if direct:
        return str(direct).strip()
    for key in ("checkout_session", "session", "checkout", "data"):
        nested = data.get(key)
        if isinstance(nested, dict):
            found = extract_processor_entity(nested)
            if found:
                return found
    return ""


def chatgpt_accept_language(req: LongLinkRequest) -> str:
    return stripe_accept_language(req)


def build_chatgpt_session(req: LongLinkRequest) -> Any:
    access_token = normalize_access_token(req.access_token)
    if not access_token:
        raise HTTPException(status_code=400, detail="accessToken is required")

    device_id = req.device_id.strip() or str(uuid.uuid4())
    user_agent = req.user_agent.strip() or DEFAULT_USER_AGENT
    accept_language = chatgpt_accept_language(req)
    oai_language = accept_language.split(",", 1)[0].split(";", 1)[0].strip() or "en-US"
    session = new_session()
    session.headers.update(
        {
            "User-Agent": user_agent,
            "Accept": "*/*",
            "Accept-Language": accept_language,
            "Authorization": f"Bearer {access_token}",
            "Origin": "https://chatgpt.com",
            "Referer": "https://chatgpt.com/",
            "Content-Type": "application/json",
            "oai-device-id": device_id,
            "oai-language": oai_language,
            "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "Cookie": f"oai-did={device_id}",
        }
    )
    set_proxy(session, checkout_stage_proxy(req))
    return session


def create_checkout(req: LongLinkRequest, chatgpt_session: Any | None = None) -> dict[str, Any]:
    billing_country = effective_country(req)
    currency = currency_for_country(billing_country)
    checkout_ui_mode = (req.checkout_ui_mode or "hosted").strip() or "hosted"
    body = {
        "entry_point": "all_plans_pricing_modal",
        "plan_name": "chatgptplusplan",
        "billing_details": {
            "country": billing_country,
            "currency": currency,
        },
        "promo_campaign": {
            "promo_campaign_id": "plus-1-month-free",
            "is_coupon_from_query_param": False,
        },
        "checkout_ui_mode": checkout_ui_mode,
    }
    headers = {
        "Referer": "https://chatgpt.com/",
        "x-openai-target-path": "/backend-api/payments/checkout",
        "x-openai-target-route": "/backend-api/payments/checkout",
    }
    response = (chatgpt_session or build_chatgpt_session(req)).post(
        "https://chatgpt.com/backend-api/payments/checkout",
        json=body,
        headers=headers,
        timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code >= 400:
        body_text = response.text[:500] if response.text else ""
        if "cannot combine currencies" in body_text.lower():
            raise HTTPException(
                status_code=409,
                detail=(
                    "GoPay needs an IDR checkout, but this Stripe customer already has active USD "
                    "checkout/subscription state. Use a fresh account/customer or wait for the USD "
                    "checkout state to expire; this cannot be bypassed in code."
                ),
            )
        raise HTTPException(
            status_code=response.status_code,
            detail=f"checkout create failed: {body_text}",
        )

    data = response.json() or {}
    cs_id = data.get("checkout_session_id") or data.get("session_id") or data.get("id")
    if not cs_id or not str(cs_id).startswith("cs_"):
        raise HTTPException(status_code=502, detail=f"checkout response missing cs_id: {data}")
    return {
        "cs_id": str(cs_id),
        "processor_entity": extract_processor_entity(data),
        "billing_country": billing_country,
        "currency": currency,
    }


def stripe_init(
    cs_id: str,
    req: LongLinkRequest,
    proxy_override: str = "",
    stripe_session: Any | None = None,
) -> dict[str, Any]:
    stripe_pk = req.stripe_publishable_key.strip() or DEFAULT_STRIPE_PK
    browser_locale, elements_locale = locale_parts(req.payment_locale)
    stripe_js_id = str(uuid.uuid4())
    stripe = stripe_session or new_session()
    stripe.headers.update(
        {
            "User-Agent": req.user_agent.strip() or DEFAULT_USER_AGENT,
            "Accept-Language": stripe_accept_language(req),
        }
    )
    if proxy_override:
        set_proxy_url(stripe, proxy_override)
    else:
        set_proxy(stripe, checkout_stage_proxy(req))
    runtime_proxy = proxy_runtime_details(stripe, proxy_override or checkout_stage_proxy(req))
    body = {
        "browser_locale": browser_locale,
        "browser_timezone": stripe_timezone_for_req(req),
        "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
        "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[stripe_js_id]": stripe_js_id,
        "elements_session_client[locale]": elements_locale,
        "elements_session_client[is_aggregation_expected]": "false",
        "elements_options_client[saved_payment_method][enable_save]": "never",
        "elements_options_client[saved_payment_method][enable_redisplay]": "never",
        "key": stripe_pk,
        "_stripe_version": STRIPE_VERSION_FULL,
    }
    response = stripe.post(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}/init",
        data=body,
        timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"stripe init failed: {response.text[:500]}",
        )
    payload = response.json() or {}
    if isinstance(payload, dict):
        payload.setdefault("_runtime_proxy", runtime_proxy)
        payload.setdefault("_stripe_js_id", stripe_js_id)
        payload.setdefault("_elements_locale", elements_locale)
    return payload


def stripe_init_gopay_checksum(stripe: Any, cs_id: str, stripe_pk: str, req: LongLinkRequest) -> str:
    browser_locale, elements_locale = locale_parts(req.payment_locale)
    body = {
        "browser_locale": browser_locale,
        "browser_timezone": "Asia/Shanghai",
        "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
        "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[stripe_js_id]": str(uuid.uuid4()),
        "elements_session_client[locale]": elements_locale,
        "elements_session_client[is_aggregation_expected]": "false",
        "key": stripe_pk,
    }
    response = stripe.post(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}/init",
        data=body,
        timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=f"stripe gopay init failed: {response.text[:500]}")
    checksum = str((response.json() or {}).get("init_checksum") or "").strip()
    if not checksum:
        raise HTTPException(status_code=502, detail=f"stripe gopay init missing init_checksum: {response.text[:300]}")
    return checksum


def to_openai_pay_url(stripe_hosted_url: str) -> str:
    url = str(stripe_hosted_url or "").strip()
    if not url:
        return ""
    if url.startswith("https://checkout.stripe.com"):
        return "https://pay.openai.com" + url[len("https://checkout.stripe.com") :]

    parsed = urlsplit(url)
    if parsed.netloc.lower() == "checkout.stripe.com":
        return urlunsplit((parsed.scheme or "https", "pay.openai.com", parsed.path, parsed.query, parsed.fragment))
    return url


def processor_entity_for_country(country: str, processor_entity: str = "") -> str:
    entity = str(processor_entity or "").strip()
    if entity:
        return entity
    return "openai_llc" if str(country or "").upper() == "US" else "openai_ie"


def chatgpt_success_return_url(cs_id: str, country: str, processor_entity: str = "") -> str:
    entity = processor_entity_for_country(country, processor_entity)
    return f"https://chatgpt.com/checkout/verify?stripe_session_id={cs_id}&processor_entity={entity}&plan_type=plus"


def stripe_checkout_long_url(cs_id: str, country: str, processor_entity: str = "") -> str:
    return (
        f"https://checkout.stripe.com/c/pay/{cs_id}"
        f"?returned_from_redirect=true&ui_mode=custom&return_url="
        f"{quote(chatgpt_success_return_url(cs_id, country, processor_entity), safe='')}"
    )


def stripe_confirm_return_url(cs_id: str, checkout: dict[str, Any], stripe_hosted_url: str) -> str:
    hosted_url = to_openai_pay_url(stripe_hosted_url) or stripe_checkout_long_url(
        cs_id,
        checkout["billing_country"],
        checkout.get("processor_entity", ""),
    )
    if "pay.openai.com/" in hosted_url or "checkout.stripe.com/" in hosted_url:
        parsed = urlsplit(hosted_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.setdefault(
            "success_return_url",
            chatgpt_success_return_url(
                cs_id,
                checkout["billing_country"],
                checkout.get("processor_entity", ""),
            ),
        )
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))
    return hosted_url


def expected_amount(init_payload: Any) -> str:
    if not isinstance(init_payload, dict):
        return "0"
    total_summary = init_payload.get("total_summary")
    if isinstance(total_summary, dict) and total_summary.get("due") is not None:
        return str(total_summary.get("due"))
    invoice = init_payload.get("invoice")
    if isinstance(invoice, dict) and invoice.get("amount_due") is not None:
        return str(invoice.get("amount_due"))
    line_items = init_payload.get("line_items")
    if isinstance(line_items, list):
        total = 0
        found = False
        for item in line_items:
            if isinstance(item, dict) and item.get("amount") is not None:
                try:
                    total += int(item.get("amount") or 0)
                    found = True
                except Exception:
                    pass
        if found:
            return str(total)
    return "0"


def stripe_context(cs_id: str, init_payload: dict[str, Any], req: LongLinkRequest) -> dict[str, Any]:
    _, elements_locale = locale_parts(req.payment_locale)
    return {
        "stripe_js_id": str(init_payload.get("_stripe_js_id") or uuid.uuid4()),
        "elements_session_id": f"elements_session_{uuid.uuid4().hex[:11]}",
        "elements_session_config_id": str(init_payload.get("config_id") or uuid.uuid4()),
        "config_id": init_payload.get("config_id") or "",
        "init_checksum": init_payload.get("init_checksum") or "",
        "currency": str(init_payload.get("currency") or currency_for_country(effective_country(req))).lower(),
        "checkout_amount": expected_amount(init_payload),
        "locale": str(init_payload.get("_elements_locale") or elements_locale),
    }


def billing_for_link_type(link_type: str, country: str = "US") -> dict[str, str]:
    normalized = normalize_link_type(link_type)
    billing_country = normalize_country(country or "US")
    if normalized == "paypal":
        if billing_country == "DE":
            first_name, last_name = random.choice(DE_BILLING_NAMES)
            line1, city, state, postal_code = random.choice(DE_BILLING_STREETS)
        elif billing_country == "JP":
            first_name, last_name = random.choice(JAPAN_BILLING_NAMES)
            line1, city, state, postal_code = random.choice(JAPAN_BILLING_STREETS)
        else:
            first_name, last_name = random.choice(US_BILLING_NAMES)
            line1, city, state, postal_code = random.choice(US_BILLING_STREETS)
        suffix = random.randint(1000, 9999)
        email_local = f"{first_name.lower()}.{last_name.lower()}{suffix}".replace("ü", "u").replace("ö", "o").replace("ä", "a")
        return {
            "name": f"{first_name} {last_name}",
            "email": f"{email_local}@example.com",
            "country": billing_country,
            "line1": line1,
            "city": city,
            "state": state,
            "postal_code": postal_code,
        }
    if normalized == "gopay":
        first_name, last_name = random.choice(INDONESIA_BILLING_NAMES)
        line1, city, state, postal_code = random.choice(INDONESIA_BILLING_STREETS)
        suffix = random.randint(1000, 9999)
        return {
            "name": f"{first_name} {last_name}",
            "email": f"{first_name.lower()}.{last_name.lower()}{suffix}@example.com",
            "country": "ID",
            "line1": line1,
            "city": city,
            "state": state,
            "postal_code": postal_code,
        }
    first_name, last_name = random.choice(US_BILLING_NAMES)
    line1, city, state, postal_code = random.choice(US_BILLING_STREETS)
    suffix = random.randint(1000, 9999)
    return {
        "name": f"{first_name} {last_name}",
        "email": f"{first_name.lower()}.{last_name.lower()}{suffix}@example.com",
        "country": "US",
        "line1": line1,
        "city": city,
        "state": state,
        "postal_code": postal_code,
    }


def stripe_accept_language(req: LongLinkRequest) -> str:
    strategy = normalize_payment_strategy(req.payment_strategy)
    profile = PAYMENT_STRATEGY_PROFILES.get(strategy) or {}
    if profile.get("accept_language"):
        return str(profile["accept_language"])
    if effective_country(req) == "DE":
        return "de-DE,de;q=0.9,en;q=0.8"
    return "en-US,en;q=0.9"


def build_stripe_session(req: LongLinkRequest, proxy_override: str = "") -> Any:
    stripe = new_session()
    stripe.headers.update(
        {
            "User-Agent": req.user_agent.strip() or DEFAULT_USER_AGENT,
            "Accept-Language": stripe_accept_language(req),
        }
    )
    if proxy_override:
        set_proxy_url(stripe, proxy_override)
    else:
        set_proxy(stripe, checkout_stage_proxy(req))
    return stripe


def stripe_create_payment_method(
    stripe: Any,
    cs_id: str,
    stripe_pk: str,
    billing: dict[str, str],
    payment_method_type: str,
    ctx: dict[str, Any],
) -> str:
    payment_method_type = normalize_link_type(payment_method_type)
    if payment_method_type == "gopay":
        body = {
            "billing_details[name]": billing.get("name") or "Budi Santoso",
            "billing_details[email]": billing.get("email") or "buyer@example.com",
            "billing_details[address][country]": billing.get("country") or "ID",
            "billing_details[address][line1]": billing.get("line1") or "Jl. Jend. Sudirman No. 1",
            "billing_details[address][city]": billing.get("city") or "Jakarta",
            "billing_details[address][postal_code]": billing.get("postal_code") or "10210",
            "billing_details[address][state]": billing.get("state") or "DKI Jakarta",
            "type": "gopay",
            "client_attribution_metadata[checkout_session_id]": cs_id,
            "key": stripe_pk,
        }
    else:
        runtime_version = str(ctx.get("runtime_version") or DEFAULT_STRIPE_RUNTIME_VERSION)
        body = {
            "billing_details[name]": billing.get("name") or "John Doe",
            "billing_details[email]": billing.get("email") or "buyer@example.com",
            "billing_details[address][country]": billing.get("country") or "US",
            "billing_details[address][line1]": billing.get("line1") or "3110 Sunset Boulevard",
            "billing_details[address][city]": billing.get("city") or "Los Angeles",
            "billing_details[address][postal_code]": billing.get("postal_code") or "90026",
            "billing_details[address][state]": billing.get("state") or "CA",
            "type": "paypal",
            "payment_user_agent": f"stripe.js/{runtime_version}; stripe-js-v3/{runtime_version}; payment-element; deferred-intent",
            "referrer": "https://chatgpt.com",
            "time_on_page": str(random.randint(25000, 55000)),
            "client_attribution_metadata[checkout_session_id]": cs_id,
            "client_attribution_metadata[client_session_id]": ctx["stripe_js_id"],
            "client_attribution_metadata[checkout_config_id]": ctx.get("config_id") or "",
            "client_attribution_metadata[elements_session_id]": ctx["elements_session_id"],
            "client_attribution_metadata[elements_session_config_id]": ctx["elements_session_config_id"],
            "client_attribution_metadata[merchant_integration_source]": "elements",
            "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
            "client_attribution_metadata[merchant_integration_version]": "2021",
            "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
            "client_attribution_metadata[payment_method_selection_flow]": "automatic",
            "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
            "client_attribution_metadata[merchant_integration_additional_elements][1]": "address",
            "key": stripe_pk,
            "_stripe_version": STRIPE_VERSION_FULL,
        }
    response = stripe.post("https://api.stripe.com/v1/payment_methods", data=body, timeout=DEFAULT_TIMEOUT)
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=f"stripe payment_methods failed: {response.text[:500]}")
    pm_id = str((response.json() or {}).get("id") or "")
    if not pm_id.startswith("pm_"):
        raise HTTPException(status_code=502, detail=f"stripe payment_methods bad response: {response.text[:300]}")
    return pm_id


def stripe_confirm(
    stripe: Any,
    cs_id: str,
    pm_id: str,
    stripe_pk: str,
    payment_method_type: str,
    init_payload: dict[str, Any],
    ctx: dict[str, Any],
    checkout: dict[str, Any],
    req: LongLinkRequest,
    stripe_hosted_url: str,
) -> dict[str, Any]:
    payment_method_type = normalize_link_type(payment_method_type)
    return_url = stripe_confirm_return_url(cs_id, checkout, stripe_hosted_url)
    if payment_method_type == "gopay":
        init_checksum = stripe_init_gopay_checksum(stripe, cs_id, stripe_pk, req)
        body = {
            "guid": uuid.uuid4().hex,
            "muid": uuid.uuid4().hex,
            "sid": uuid.uuid4().hex,
            "payment_method": pm_id,
            "init_checksum": init_checksum,
            "version": "fed52f3bc6",
            "expected_amount": "0",
            "expected_payment_method_type": "gopay",
            "return_url": return_url,
            "elements_session_client[session_id]": f"elements_session_{uuid.uuid4().hex[:11]}",
            "elements_session_client[locale]": locale_parts(req.payment_locale)[1],
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[is_aggregation_expected]": "false",
            "client_attribution_metadata[client_session_id]": str(uuid.uuid4()),
            "client_attribution_metadata[merchant_integration_source]": "elements",
            "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
            "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
            "consent[terms_of_service]": "accepted",
            "key": stripe_pk,
        }
    else:
        runtime_version = str(ctx.get("runtime_version") or DEFAULT_STRIPE_RUNTIME_VERSION)
        body = {
            "guid": uuid.uuid4().hex,
            "muid": uuid.uuid4().hex,
            "sid": uuid.uuid4().hex,
            "payment_method": pm_id,
            "init_checksum": str(init_payload.get("init_checksum") or ctx.get("init_checksum") or ""),
            "version": runtime_version,
            "expected_amount": str(ctx.get("checkout_amount") or expected_amount(init_payload)),
            "expected_payment_method_type": "paypal",
            "return_url": return_url,
            "elements_session_client[session_id]": ctx["elements_session_id"],
            "elements_session_client[locale]": str(ctx.get("locale") or "en"),
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[is_aggregation_expected]": "false",
            "elements_session_client[elements_init_source]": "custom_checkout",
            "elements_session_client[stripe_js_id]": ctx["stripe_js_id"],
            "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
            "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
            "elements_options_client[saved_payment_method][enable_save]": "never",
            "elements_options_client[saved_payment_method][enable_redisplay]": "never",
            "client_attribution_metadata[client_session_id]": ctx["stripe_js_id"],
            "client_attribution_metadata[checkout_session_id]": cs_id,
            "client_attribution_metadata[checkout_config_id]": ctx.get("config_id") or "",
            "client_attribution_metadata[elements_session_id]": ctx["elements_session_id"],
            "client_attribution_metadata[elements_session_config_id]": ctx["elements_session_config_id"],
            "client_attribution_metadata[merchant_integration_source]": "checkout",
            "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
            "client_attribution_metadata[merchant_integration_version]": "custom",
            "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
            "client_attribution_metadata[payment_method_selection_flow]": "automatic",
            "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
            "client_attribution_metadata[merchant_integration_additional_elements][1]": "address",
            "consent[terms_of_service]": "accepted",
            "key": stripe_pk,
            "_stripe_version": STRIPE_VERSION_FULL,
        }
    response = stripe.post(f"https://api.stripe.com/v1/payment_pages/{cs_id}/confirm", data=body, timeout=DEFAULT_TIMEOUT)
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=f"stripe confirm failed: {response.text[:500]}")
    return response.json() or {}


def extract_redirect_to_url(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    next_action = payload.get("next_action")
    if isinstance(next_action, dict) and next_action.get("type") == "redirect_to_url":
        redirect_to_url = next_action.get("redirect_to_url") or {}
        if isinstance(redirect_to_url, dict):
            url = str(redirect_to_url.get("url") or "").strip()
            if url:
                return url
    for key in ("setup_intent", "payment_intent"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            found = extract_redirect_to_url(nested)
            if found:
                return found
    return ""


def extract_nested_redirect_urls(payload: Any, preferred_hosts: tuple[str, ...] = ()) -> list[str]:
    preferred = _preferred_hosts(preferred_hosts)
    fallback_pattern = re.compile(r"pm-redirects\.stripe\.com|paypal\.com/agreements", re.I)
    found: list[str] = []
    seen: set[str] = set()
    for value in iter_nested_values(payload):
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text.startswith("http"):
            continue
        if preferred and url_matches_hosts(text, preferred):
            if text not in seen:
                seen.add(text)
                found.append(text)
            continue
        if fallback_pattern.search(text) and text not in seen:
            seen.add(text)
            found.append(text)
    return found


def stripe_poll_proxy_candidates(checkout_proxy: str = "", provider_proxy: str = "") -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for label, proxy in (
        ("checkout", checkout_proxy),
        ("provider", provider_proxy),
    ):
        normalized = str(proxy or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        candidates.append((label, normalized))
    if not candidates:
        candidates.append(("direct", ""))
    return candidates


def apply_poll_proxy(stripe: Any, proxy: str) -> None:
    if proxy:
        set_proxy_url(stripe, proxy)
    else:
        stripe.proxies = {}


def fetch_hosted_redirect_candidates(
    stripe: Any,
    hosted_long_url: str,
    preferred_hosts: tuple[str, ...] = (),
) -> str:
    hosted_long_url = str(hosted_long_url or "").strip()
    if not hosted_long_url:
        return ""
    preferred = preferred_hosts or ("paypal.com", "pm-redirects.stripe.com")
    try:
        response = stripe.get(hosted_long_url, timeout=DEFAULT_TIMEOUT)
    except Exception:
        response = None
    if response is not None and int(getattr(response, "status_code", 0) or 0) == 200:
        body_text = str(getattr(response, "text", "") or "")
        for candidate in extract_external_url_candidates(body_text, preferred):
            resolved = resolve_external_redirect(stripe, candidate, preferred_hosts=preferred, max_hops=8)
            if is_actionable_stripe_redirect(resolved, preferred):
                return resolved
    return resolve_external_redirect(stripe, hosted_long_url, preferred_hosts=preferred, max_hops=8)


def stripe_finalize_after_approve(
    stripe: Any,
    cs_id: str,
    pm_id: str,
    stripe_pk: str,
    link_type: str,
    init_payload: dict[str, Any],
    ctx: dict[str, Any],
    checkout: dict[str, Any],
    req: LongLinkRequest,
    stripe_hosted_url: str,
    confirm_payload: dict[str, Any] | None = None,
    progress: ProgressLogger = noop_progress,
) -> str:
    preferred_hosts = ("paypal.com", "pm-redirects.stripe.com")
    if not pm_id:
        return ""
    progress("redirect_poll", "approve 已通过，尝试二次 confirm 获取 PayPal redirect。")
    reconfirm_payload: dict[str, Any] = {}
    try:
        reconfirm_payload = stripe_confirm(
            stripe,
            cs_id,
            pm_id,
            stripe_pk,
            link_type,
            init_payload,
            ctx,
            checkout,
            req,
            stripe_hosted_url,
        )
    except HTTPException as exc:
        progress("redirect_poll", f"二次 confirm 暂未返回 redirect：{exc.detail}")
        if isinstance(confirm_payload, dict):
            reconfirm_payload = confirm_payload
    redirect_url = extract_redirect_to_url(reconfirm_payload)
    if redirect_url and is_actionable_stripe_redirect(redirect_url, preferred_hosts):
        progress("redirect_poll", "二次 confirm 已直接返回 redirect。")
        return redirect_url
    for candidate in extract_nested_redirect_urls(reconfirm_payload, preferred_hosts):
        if is_actionable_stripe_redirect(candidate, preferred_hosts):
            progress("redirect_poll", "二次 confirm 深层字段命中 redirect。")
            return candidate
    setup_redirect = poll_setup_intent_redirect_from_confirm(stripe, reconfirm_payload, stripe_pk, preferred_hosts)
    if setup_redirect:
        progress("redirect_poll", "二次 confirm 后 SetupIntent 回查命中 redirect。")
        return setup_redirect
    return ""


def poll_setup_intent_redirect_from_confirm(
    stripe: Any,
    confirm_payload: dict[str, Any] | None,
    stripe_pk: str,
    preferred_hosts: tuple[str, ...] = (),
) -> str:
    if not isinstance(confirm_payload, dict):
        return ""
    preferred = preferred_hosts or ("paypal.com", "pm-redirects.stripe.com")
    setup_intent_id, client_secret = extract_setup_intent_reference(confirm_payload)
    if not setup_intent_id or not client_secret:
        return ""
    try:
        response = stripe.get(
            f"https://api.stripe.com/v1/setup_intents/{setup_intent_id}",
            params={
                "key": stripe_pk,
                "client_secret": client_secret,
                "_stripe_version": STRIPE_VERSION_FULL,
            },
            timeout=DEFAULT_TIMEOUT,
        )
    except Exception:
        return ""
    if response.status_code != 200:
        return ""
    payload = response.json() or {}
    redirect_url = extract_redirect_to_url(payload)
    if redirect_url and is_actionable_stripe_redirect(redirect_url, preferred):
        return redirect_url
    for candidate in extract_nested_redirect_urls(payload, preferred):
        if is_actionable_stripe_redirect(candidate, preferred):
            return candidate
    return ""


def post_approve_redirect_recovery(
    stripe: Any,
    cs_id: str,
    stripe_pk: str,
    req: LongLinkRequest,
    ctx: dict[str, Any] | None = None,
    *,
    hosted_long_url: str = "",
    checkout_proxy: str = "",
    provider_proxy: str = "",
    timeout_seconds: float = 45,
    progress: ProgressLogger = noop_progress,
    confirm_payload: dict[str, Any] | None = None,
    pm_id: str = "",
    link_type: str = "paypal",
    init_payload: dict[str, Any] | None = None,
    checkout: dict[str, Any] | None = None,
    stripe_hosted_url: str = "",
) -> str:
    preferred_hosts = ("paypal.com", "pm-redirects.stripe.com")
    deadline = time.time() + max(12.0, float(timeout_seconds or 45))
    proxies = stripe_poll_proxy_candidates(checkout_proxy, provider_proxy)
    attempt = 0
    if pm_id and init_payload is not None and checkout is not None:
        for label, proxy in proxies:
            session = clone_http_session(stripe)
            apply_poll_proxy(session, proxy)
            finalized = stripe_finalize_after_approve(
                session,
                cs_id,
                pm_id,
                stripe_pk,
                link_type,
                init_payload,
                ctx or {},
                checkout,
                req,
                stripe_hosted_url,
                confirm_payload=confirm_payload,
                progress=progress,
            )
            if finalized and is_actionable_stripe_redirect(finalized, preferred_hosts):
                return finalized
    while time.time() < deadline:
        attempt += 1
        for label, proxy in proxies:
            session = clone_http_session(stripe)
            apply_poll_proxy(session, proxy)
            redirect_url = poll_setup_intent_redirect_from_confirm(
                session,
                confirm_payload,
                stripe_pk,
                preferred_hosts=preferred_hosts,
            )
            if redirect_url and is_actionable_stripe_redirect(redirect_url, preferred_hosts):
                progress(
                    "redirect_poll",
                    f"approve 后 SetupIntent 回查命中 redirect（{label} 代理）。",
                    {"redirect_url": redirect_url, "poll_proxy": safe_proxy_hint(proxy), "attempt": attempt},
                )
                return redirect_url
            redirect_url = probe_stripe_redirect_sources(
                session,
                cs_id,
                stripe_pk,
                req,
                ctx=ctx,
                hosted_long_url=hosted_long_url,
                preferred_hosts=preferred_hosts,
                deep_scan=True,
            )
            if redirect_url and is_actionable_stripe_redirect(redirect_url, preferred_hosts):
                progress(
                    "redirect_poll",
                    f"approve 后恢复轮询命中 redirect（{label} 代理）。",
                    {"redirect_url": redirect_url, "poll_proxy": safe_proxy_hint(proxy), "attempt": attempt},
                )
                return redirect_url
        if attempt == 1 or attempt % 10 == 0:
            progress(
                "redirect_poll",
                f"approve 已通过，继续双代理恢复轮询，第 {attempt} 轮。",
                {"attempt": attempt, "proxies": [safe_proxy_hint(proxy) for _, proxy in proxies if proxy]},
            )
        time.sleep(0.45 if attempt < 30 else 0.9)
    return ""


def _preferred_hosts(preferred_hosts: tuple[str, ...] = ()) -> tuple[str, ...]:
    return tuple(str(host or "").strip().lower().lstrip(".") for host in preferred_hosts if str(host or "").strip())


def url_matches_hosts(url: str, preferred_hosts: tuple[str, ...] = ()) -> bool:
    normalized = _preferred_hosts(preferred_hosts)
    if not normalized:
        return False
    host = (urlsplit(str(url or "").strip()).netloc or "").lower()
    return any(host == item or host.endswith(f".{item}") for item in normalized)


def iter_nested_values(payload: Any) -> Iterator[Any]:
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            yield from iter_nested_values(value)
        return
    if isinstance(payload, (list, tuple)):
        for value in payload:
            yield from iter_nested_values(value)
        return
    yield payload


def extract_setup_intent_reference(payload: Any) -> tuple[str, str]:
    client_secret = ""
    setup_intent_id = ""
    for value in iter_nested_values(payload):
        if isinstance(value, dict):
            if str(value.get("object") or "").strip() == "setup_intent":
                nested_id = str(value.get("id") or "").strip()
                nested_secret = str(value.get("client_secret") or "").strip()
                if nested_secret and not client_secret:
                    client_secret = nested_secret
                if nested_id and not setup_intent_id:
                    setup_intent_id = nested_id
            for key in ("setup_intent_client_secret", "client_secret"):
                nested_secret = str(value.get(key) or "").strip()
                if nested_secret.startswith("seti_") and "_secret_" in nested_secret and not client_secret:
                    client_secret = nested_secret
            nested_id = str(value.get("setup_intent") or "").strip()
            if nested_id.startswith("seti_") and not setup_intent_id:
                setup_intent_id = nested_id
            continue
        if not isinstance(value, str):
            continue
        if not client_secret:
            match = re.search(r"(seti_[A-Za-z0-9]+_secret_[A-Za-z0-9]+)", value)
            if match:
                client_secret = match.group(1)
        if not setup_intent_id:
            match = re.search(r"(seti_[A-Za-z0-9]+)", value)
            if match:
                setup_intent_id = match.group(1)
        if client_secret and setup_intent_id:
            break
    if client_secret and not setup_intent_id:
        setup_intent_id = client_secret.split("_secret_", 1)[0]
    return setup_intent_id, client_secret


def stripe_setup_intent_redirect_url_from_payload(stripe: Any, payload: Any, stripe_pk: str) -> str:
    setup_intent_id, client_secret = extract_setup_intent_reference(payload)
    if not setup_intent_id or not client_secret:
        return ""
    try:
        response = stripe.get(
            f"https://api.stripe.com/v1/setup_intents/{setup_intent_id}",
            params={
                "key": stripe_pk,
                "client_secret": client_secret,
                "_stripe_version": STRIPE_VERSION_FULL,
            },
            timeout=DEFAULT_TIMEOUT,
        )
    except Exception:
        return ""
    if response.status_code != 200:
        return ""
    setup_payload = response.json() or {}
    redirect_url = extract_redirect_to_url(setup_payload)
    if redirect_url:
        return redirect_url
    terminal_error = extract_stripe_terminal_error(setup_payload)
    if terminal_error:
        raise HTTPException(status_code=502, detail=terminal_error)
    return ""


def extract_external_url_candidates(text: str, preferred_hosts: tuple[str, ...] = ()) -> list[str]:
    if not text:
        return []
    allowed_fallback_hosts = ("paypal.com", "hooks.stripe.com", "pm-redirects.stripe.com", "checkout.stripe.com", "pay.openai.com")
    candidates: list[str] = []
    seen: set[str] = set()
    variants = [
        text,
        html_unescape(text),
        text.replace("\\/", "/"),
        html_unescape(text).replace("\\/", "/"),
    ]
    for variant in variants:
        for match in re.findall(r"https?://[^\s\"'<>\\\\]+", variant):
            candidate = match.rstrip(")]};,'\"")
            if not candidate:
                continue
            host = (urlsplit(candidate).netloc or "").lower()
            if preferred_hosts and not url_matches_hosts(candidate, preferred_hosts):
                if not any(host == item or host.endswith(f".{item}") for item in allowed_fallback_hosts):
                    continue
            if candidate in seen:
                continue
            seen.add(candidate)
            candidates.append(candidate)
    if preferred_hosts:
        preferred = [candidate for candidate in candidates if url_matches_hosts(candidate, preferred_hosts)]
        if preferred:
            return preferred
    return candidates


def stripe_payment_page_redirect_url(stripe: Any, cs_id: str, stripe_pk: str, req: LongLinkRequest, timeout_seconds: float = 30) -> str:
    deadline = time.time() + max(1.0, float(timeout_seconds or 30))
    last_err = ""
    params = {
        "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
        "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[session_id]": f"elements_session_{uuid.uuid4().hex[:11]}",
        "elements_session_client[stripe_js_id]": str(uuid.uuid4()),
        "elements_session_client[locale]": locale_parts(req.payment_locale)[1],
        "elements_session_client[is_aggregation_expected]": "false",
        "elements_options_client[saved_payment_method][enable_save]": "never",
        "elements_options_client[saved_payment_method][enable_redisplay]": "never",
        "key": stripe_pk,
        "_stripe_version": STRIPE_VERSION_FULL,
    }
    while time.time() < deadline:
        response = stripe.get(f"https://api.stripe.com/v1/payment_pages/{cs_id}", params=params, timeout=DEFAULT_TIMEOUT)
        if response.status_code == 200:
            payload = response.json() or {}
            redirect_url = extract_redirect_to_url(payload)
            if redirect_url:
                return redirect_url
            redirect_url = stripe_setup_intent_redirect_url_from_payload(stripe, payload, stripe_pk)
            if redirect_url:
                return redirect_url
            last_err = f"keys=[{','.join(sorted(payload.keys())[:8])}]"
        else:
            last_err = f"http {response.status_code}: {response.text[:120]}"
        time.sleep(1)
    raise HTTPException(status_code=504, detail=f"redirect url resolution timeout: {last_err}")


def chatgpt_approve(chatgpt: Any, cs_id: str, checkout: dict[str, Any]) -> None:
    country = checkout["billing_country"]
    processor_entity = processor_entity_for_country(country, checkout.get("processor_entity", ""))
    try:
        chatgpt.post(
            "https://chatgpt.com/backend-api/sentinel/ping",
            json={},
            headers={
                "Referer": "https://chatgpt.com/",
                "x-openai-target-path": "/backend-api/sentinel/ping",
                "x-openai-target-route": "/backend-api/sentinel/ping",
            },
            timeout=DEFAULT_TIMEOUT,
        )
    except Exception:
        pass
    response = chatgpt.post(
        "https://chatgpt.com/backend-api/payments/checkout/approve",
        json={"checkout_session_id": cs_id, "processor_entity": processor_entity},
        headers={
            "Referer": f"https://chatgpt.com/checkout/{processor_entity}/{cs_id}",
            "x-openai-target-path": "/backend-api/payments/checkout/approve",
            "x-openai-target-route": "/backend-api/payments/checkout/approve",
        },
        timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=f"chatgpt approve failed: {response.text[:500]}")
    try:
        result = (response.json() or {}).get("result")
    except Exception:
        result = ""
    if result != "approved":
        raise HTTPException(status_code=502, detail=f"chatgpt approve unexpected result: {result!r}")


def redirect_url_after_confirm(
    chatgpt: Any,
    stripe: Any,
    confirm_payload: dict[str, Any],
    cs_id: str,
    stripe_pk: str,
    checkout: dict[str, Any],
    req: LongLinkRequest,
) -> str:
    redirect_url = extract_redirect_to_url(confirm_payload)
    if redirect_url:
        return redirect_url
    submission = confirm_payload.get("submission_attempt") if isinstance(confirm_payload, dict) else None
    if isinstance(submission, dict) and submission.get("state") == "requires_approval":
        chatgpt_approve(chatgpt, cs_id, checkout)
        return stripe_payment_page_redirect_url(stripe, cs_id, stripe_pk, req, timeout_seconds=45)
    return stripe_payment_page_redirect_url(stripe, cs_id, stripe_pk, req, timeout_seconds=30)


def resolve_external_redirect(stripe: Any, redirect_url: str, preferred_hosts: tuple[str, ...] = (), max_hops: int = 5) -> str:
    current = str(redirect_url or "").strip()
    preferred = _preferred_hosts(preferred_hosts)
    for _ in range(max(1, int(max_hops or 1))):
        if not current:
            return ""
        if url_matches_hosts(current, preferred):
            return current
        try:
            response = stripe.get(current, allow_redirects=False, timeout=DEFAULT_TIMEOUT)
        except Exception:
            return current
        resolved_url = str(getattr(response, "url", "") or current).strip()
        if url_matches_hosts(resolved_url, preferred):
            return resolved_url
        if response.status_code in (301, 302, 303, 307, 308):
            location = str(response.headers.get("Location") or "").strip()
            if not location:
                return resolved_url or current
            current = urljoin(current, location)
            continue
        body_text = str(getattr(response, "text", "") or "")
        for candidate in extract_external_url_candidates(body_text, preferred):
            if candidate == current:
                continue
            current = candidate
            break
        else:
            return resolved_url or current
    return current


def create_provider_link(
    chatgpt: Any,
    checkout: dict[str, Any],
    init_payload: dict[str, Any],
    stripe_hosted_url: str,
    req: LongLinkRequest,
    provider_proxy: str = "",
) -> dict[str, str]:
    link_type = normalize_link_type(req.link_type)
    stripe_pk = req.stripe_publishable_key.strip() or DEFAULT_STRIPE_PK
    stripe = build_stripe_session(req, proxy_override=provider_proxy)
    ctx = stripe_context(checkout["cs_id"], init_payload, req)
    billing = billing_for_link_type(link_type)
    pm_id = stripe_create_payment_method(stripe, checkout["cs_id"], stripe_pk, billing, link_type, ctx)
    confirm_payload = stripe_confirm(
        stripe,
        checkout["cs_id"],
        pm_id,
        stripe_pk,
        link_type,
        init_payload,
        ctx,
        checkout,
        req,
        stripe_hosted_url,
    )
    stripe_redirect_url = redirect_url_after_confirm(
        chatgpt,
        stripe,
        confirm_payload,
        checkout["cs_id"],
        stripe_pk,
        checkout,
        req,
    )
    preferred_hosts = ("paypal.com",) if link_type == "paypal" else ()
    provider_url = resolve_external_redirect(stripe, stripe_redirect_url, preferred_hosts=preferred_hosts)
    return {
        "payment_method_id": pm_id,
        "stripe_redirect_url": stripe_redirect_url,
        "provider_redirect_url": provider_url,
        "long_url": provider_url or stripe_redirect_url,
    }


class TaskCancelled(RuntimeError):
    pass


class PauseController:
    def __init__(self) -> None:
        self._paused = threading.Event()
        self._paused.clear()
        self._cancelled = threading.Event()

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def cancel(self) -> None:
        self._cancelled.set()
        self._paused.clear()

    def is_paused(self) -> bool:
        return self._paused.is_set()

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def raise_if_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise TaskCancelled("任务已终止")

    def wait_if_paused(self) -> bool:
        was_paused = False
        while self._paused.is_set():
            self.raise_if_cancelled()
            was_paused = True
            time.sleep(0.05)
        self.raise_if_cancelled()
        return was_paused


TASK_CONTROLLERS: dict[str, PauseController] = {}
TASK_CONTROLLERS_LOCK = threading.Lock()


def normalize_task_id(task_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", str(task_id or "").strip())[:80]


def get_or_create_task_controller(task_id: str) -> PauseController:
    safe_task_id = normalize_task_id(task_id)
    if not safe_task_id:
        raise HTTPException(status_code=400, detail="taskId 无效")
    with TASK_CONTROLLERS_LOCK:
        controller = TASK_CONTROLLERS.get(safe_task_id)
        if controller is None:
            controller = PauseController()
            TASK_CONTROLLERS[safe_task_id] = controller
        return controller


def release_task_controller(task_id: str) -> None:
    safe_task_id = normalize_task_id(task_id)
    if not safe_task_id:
        return
    with TASK_CONTROLLERS_LOCK:
        TASK_CONTROLLERS.pop(safe_task_id, None)


def normalize_proxy_probe_payload(data: dict[str, Any]) -> dict[str, str]:
    if str(data.get("status") or "").lower() == "fail":
        raise RuntimeError(str(data.get("message") or "IP probe failed"))
    ip = str(data.get("ip") or data.get("query") or "").strip()
    country = str(data.get("country") or data.get("countryCode") or "").strip()
    country_code = str(data.get("countryCode") or "").strip().upper()
    country_display_map = {
        "JP": "Japan（日本）",
        "US": "United States（美国）",
        "ID": "Indonesia（印尼）",
    }
    if not country_code and len(country) == 2:
        country_code = country.upper()
    return {
        "ip": ip,
        "country": country,
        "country_code": country_code,
        "country_display": country_display_map.get(country_code, country or country_code),
        "region": str(data.get("region") or data.get("regionName") or "").strip(),
        "city": str(data.get("city") or "").strip(),
        "timezone": str(data.get("timezone") or "").strip(),
        "org": str(data.get("org") or data.get("isp") or "").strip(),
        "isp": str(data.get("isp") or data.get("org") or "").strip(),
    }


def check_proxy_info(proxy_url: str = "") -> dict[str, Any]:
    endpoints = [
        "http://ip-api.com/json?fields=status,message,query,country,countryCode,regionName,city,timezone,org,isp",
        "https://ipinfo.io/json",
    ]
    errors: list[str] = []
    for candidate in proxy_candidates(normalize_proxy_url(proxy_url)):
        for url in endpoints:
            try:
                proxies = {"http": candidate, "https": candidate} if candidate else None
                response = requests.get(url, proxies=proxies, timeout=8)
                response.raise_for_status()
            except Exception as exc:
                errors.append(f"{mask_proxy_url(candidate) or 'direct'} -> {url}: {exc}")
                if CurlCffiSession is None:
                    continue
                try:
                    probe = new_session()
                    probe.headers.update(
                        {
                            "User-Agent": DEFAULT_USER_AGENT,
                            "Accept-Language": "en-US,en;q=0.9",
                        }
                    )
                    if candidate:
                        set_proxy_url(probe, candidate)
                    response = probe.get(url, timeout=8)
                    if hasattr(response, "raise_for_status"):
                        response.raise_for_status()
                except Exception as fallback_exc:
                    errors.append(f"{mask_proxy_url(candidate) or 'direct'} -> {url} [session]: {fallback_exc}")
                    continue
            info = normalize_proxy_probe_payload(response.json() or {})
            if not info.get("ip"):
                raise RuntimeError("代理检测结果缺少 IP")
            info["proxy"] = mask_proxy_url(candidate) if candidate else "direct"
            info["proxy_url"] = candidate
            info["protocol"] = urlsplit(candidate).scheme if candidate else "direct"
            info["source"] = urlsplit(url).netloc
            return info
    raise RuntimeError("代理检测失败: " + "; ".join(errors[-3:]))

def proxy_check_item(stage: str, label: str, proxy_url: str, selection_kind: str = "", selection_source: str = "") -> ProxyCheckItem:
    proxy_url = normalize_proxy_url(proxy_url) if proxy_url else ""
    try:
        info = check_proxy_info(proxy_url)
        return ProxyCheckItem(
            stage=stage,
            label=label,
            ok=True,
            proxy_hint=safe_proxy_hint(proxy_url) if proxy_url else "direct",
            protocol=str(info.get("protocol") or ""),
            selection_kind=selection_kind,
            selection_source=selection_source,
            ip=str(info.get("ip") or ""),
            country=str(info.get("country_display") or info.get("country") or ""),
            country_code=str(info.get("country_code") or ""),
            region=str(info.get("region") or ""),
            city=str(info.get("city") or ""),
            isp=str(info.get("isp") or ""),
            org=str(info.get("org") or ""),
            source=str(info.get("source") or ""),
        )
    except Exception as exc:
        return ProxyCheckItem(
            stage=stage,
            label=label,
            ok=False,
            proxy_hint=safe_proxy_hint(proxy_url) if proxy_url else "direct",
            protocol=urlsplit(proxy_url).scheme if proxy_url else "direct",
            selection_kind=selection_kind,
            selection_source=selection_source,
            error=str(exc),
        )


def build_proxy_check_response(req: ProxyCheckRequest) -> ProxyCheckResponse:
    link_type = normalize_link_type(req.link_type)
    stage = str(req.stage or "").strip().lower()
    checks: list[ProxyCheckItem] = []
    checkout_proxy = checkout_stage_proxy(req)
    provider_proxy = provider_stage_proxy(req) if link_type in {"paypal", "gopay"} else ""
    checkout_kind = "custom" if (req.checkout_proxy or req.proxy_input or req.proxy) else "builtin"
    checkout_source = "请求代理输入" if checkout_kind == "custom" else "内置 checkout 代理"
    provider_kind = "custom" if req.provider_proxy else "builtin"
    provider_source = "前端自定义 provider 代理" if provider_kind == "custom" else "内置 provider（随账单地区切换）代理"
    if stage == "provider":
        checks.append(proxy_check_item("provider", "provider 阶段", provider_proxy, provider_kind, provider_source))
    elif stage == "checkout":
        checks.append(proxy_check_item("checkout", "checkout 阶段", checkout_proxy, checkout_kind, checkout_source))
    else:
        checks.append(proxy_check_item("checkout", "checkout 阶段", checkout_proxy, checkout_kind, checkout_source))
        if link_type in {"paypal", "gopay"}:
            checks.append(proxy_check_item("provider", "provider 阶段", provider_proxy, provider_kind, provider_source))
    ok = all(item.ok for item in checks)
    return ProxyCheckResponse(ok=ok, message="代理检测完成" if ok else "代理检测失败", checks=checks)


def legacy_proxy_info(item: ProxyCheckItem) -> dict[str, str]:
    return {
        "ip": item.ip,
        "country": item.country,
        "country_code": item.country_code,
        "country_display": item.country,
        "region": item.region,
        "city": item.city,
        "org": item.org or item.isp,
        "isp": item.isp,
        "proxy": item.proxy_hint,
        "protocol": item.protocol,
        "source": item.source,
    }


def response_from_parts(
    req: LongLinkRequest,
    link_type: str,
    checkout: dict[str, Any],
    stripe_hosted_url: str,
    hosted_long_url: str,
    provider: dict[str, str],
    fallback: bool,
    provider_error: str,
    ok: bool,
) -> LongLinkResponse:
    return LongLinkResponse(
        ok=ok,
        cs_id=checkout["cs_id"],
        processor_entity=checkout["processor_entity"],
        billing_country=checkout["billing_country"],
        currency=checkout["currency"],
        payment_locale=locale_parts(req.payment_locale)[0],
        link_type=link_type,
        payment_method_type=link_type if link_type in {"paypal", "gopay"} else "",
        payment_method_id=provider["payment_method_id"],
        stripe_redirect_url=provider["stripe_redirect_url"],
        provider_redirect_url=provider["provider_redirect_url"],
        fallback=fallback,
        provider_error=provider_error,
        stripe_hosted_url=stripe_hosted_url,
        long_url=provider["long_url"] or hosted_long_url,
        approve_result=str(provider.get("approve_result") or ""),
    )


def resolve_public_paypal_input(req: PublicPayPalLinkRequest) -> str:
    return str(req.access_token or "").strip() or str(req.session_json or "").strip()


def build_public_paypal_request(req: PublicPayPalLinkRequest) -> LongLinkRequest:
    return LongLinkRequest(
        accessToken=resolve_public_paypal_input(req),
        link_type="paypal",
        proxy=req.proxy,
        checkoutProxy=req.checkout_proxy,
        providerProxy=req.provider_proxy,
        maxRetries=req.max_retries,
        approveRetries=req.approve_retries,
    )


def build_public_paypal_success(result: LongLinkResponse) -> PublicPayPalLinkResponse:
    return PublicPayPalLinkResponse(
        success=bool(result.long_url and "paypal.com/agreements/approve" in result.long_url),
        code="SUCCESS" if result.long_url and "paypal.com/agreements/approve" in result.long_url else "PAYPAL_LINK_NOT_FOUND",
        message="ok" if result.long_url and "paypal.com/agreements/approve" in result.long_url else "not found",
        paypal_link=result.long_url if "paypal.com/agreements/approve" in result.long_url else "",
        hosted_long_url=result.long_url if result.fallback else "",
        attempt_count=result.attempt_count,
        max_attempts=result.max_attempts,
        retries_used=max(0, result.attempt_count - 1),
        cs_id=result.cs_id,
        billing_country=result.billing_country,
        currency=result.currency,
        provider_error=result.provider_error,
        last_error=result.provider_error,
        provider_redirect_url=result.provider_redirect_url,
        stripe_redirect_url=result.stripe_redirect_url,
        stripe_hosted_url=result.stripe_hosted_url,
        retry_history=result.retry_history,
    )


def build_public_paypal_failure(
    error_text: str,
    attempt_count: int,
    max_attempts: int,
    retry_history: list[RetryHistoryItem],
) -> PublicPayPalLinkResponse:
    return PublicPayPalLinkResponse(
        success=False,
        code="UPSTREAM_ERROR",
        message=error_text,
        paypal_link="",
        hosted_long_url="",
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        retries_used=max(0, attempt_count - 1),
        cs_id="",
        billing_country="",
        currency="",
        provider_error=error_text,
        last_error=error_text,
        provider_redirect_url="",
        stripe_redirect_url="",
        stripe_hosted_url="",
        retry_history=retry_history,
    )


def extract_stripe_terminal_error(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("setup_intent", "payment_intent"):
        nested = payload.get(key)
        if not isinstance(nested, dict):
            continue
        error = nested.get("last_setup_error") or nested.get("last_payment_error")
        if isinstance(error, dict):
            payment_method = error.get("payment_method") or nested.get("payment_method") or payload.get("payment_method") or {}
            payment_method_type = ""
            billing_country = ""
            if isinstance(payment_method, dict):
                payment_method_type = str(payment_method.get("type") or "").strip()
                billing_details = payment_method.get("billing_details") or {}
                if isinstance(billing_details, dict):
                    address = billing_details.get("address") or {}
                    if isinstance(address, dict):
                        billing_country = str(address.get("country") or "").strip()
            parts = [
                f"code={str(error.get('code') or '').strip()}",
                f"decline_code={str(error.get('decline_code') or '').strip()}",
                f"message={str(error.get('message') or '').strip()}",
                f"payment_method.type={payment_method_type}",
                f"billing_details.address.country={billing_country}",
            ]
            compact = [part for part in parts if not part.endswith("=")]
            if compact:
                return f"stripe terminal error: {', '.join(compact)}"
        found = extract_stripe_terminal_error(nested)
        if found:
            return found
    return ""


def is_stripe_terminal_error_detail(detail: Any) -> bool:
    return str(detail or "").startswith("stripe terminal error:")


def stripe_payment_page_params(stripe_pk: str, req: LongLinkRequest, ctx: dict[str, Any] | None = None) -> dict[str, str]:
    ctx = ctx or {}
    return {
        "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
        "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[session_id]": str(ctx.get("elements_session_id") or f"elements_session_{uuid.uuid4().hex[:11]}"),
        "elements_session_client[stripe_js_id]": str(ctx.get("stripe_js_id") or uuid.uuid4()),
        "elements_session_client[locale]": str(ctx.get("locale") or locale_parts(req.payment_locale)[1]),
        "elements_session_client[is_aggregation_expected]": "false",
        "elements_options_client[saved_payment_method][enable_save]": "never",
        "elements_options_client[saved_payment_method][enable_redisplay]": "never",
        "key": stripe_pk,
        "_stripe_version": STRIPE_VERSION_FULL,
    }


def stripe_payment_page_redirect_url_once(
    stripe: Any,
    cs_id: str,
    stripe_pk: str,
    req: LongLinkRequest,
    ctx: dict[str, Any] | None = None,
) -> str:
    response = stripe.get(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}",
        params=stripe_payment_page_params(stripe_pk, req, ctx),
        timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code != 200:
        return ""
    payload = response.json() or {}
    redirect_url = extract_redirect_to_url(payload)
    if redirect_url:
        return redirect_url
    terminal_error = extract_stripe_terminal_error(payload)
    if terminal_error:
        raise HTTPException(status_code=502, detail=terminal_error)
    redirect_url = stripe_setup_intent_redirect_url_from_payload(stripe, payload, stripe_pk)
    if redirect_url:
        return redirect_url
    return ""


def stripe_payment_page_redirect_url(
    stripe: Any,
    cs_id: str,
    stripe_pk: str,
    req: LongLinkRequest,
    ctx: dict[str, Any] | None = None,
    timeout_seconds: float = 30,
    progress: ProgressLogger = noop_progress,
) -> str:
    deadline = time.time() + max(1.0, float(timeout_seconds or 30))
    last_err = ""
    params = stripe_payment_page_params(stripe_pk, req, ctx)
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        progress("redirect_poll", f"正在轮询 Stripe 跳转地址，第 {attempt} 次。")
        response = stripe.get(f"https://api.stripe.com/v1/payment_pages/{cs_id}", params=params, timeout=DEFAULT_TIMEOUT)
        if response.status_code == 200:
            payload = response.json() or {}
            redirect_url = extract_redirect_to_url(payload)
            if redirect_url:
                progress("redirect_poll", "已从 Stripe payment page 解析到跳转地址。")
                return redirect_url
            terminal_error = extract_stripe_terminal_error(payload)
            if terminal_error:
                raise HTTPException(status_code=502, detail=terminal_error)
            redirect_url = stripe_setup_intent_redirect_url_from_payload(stripe, payload, stripe_pk)
            if redirect_url:
                progress("redirect_poll", "已通过 SetupIntent 回查拿到跳转地址。")
                return redirect_url
            last_err = f"keys=[{','.join(sorted(payload.keys())[:8])}]"
        else:
            last_err = f"http {response.status_code}: {response.text[:120]}"
        time.sleep(1)
    raise HTTPException(status_code=504, detail=f"redirect url resolution timeout: {last_err}")


def chatgpt_approve_with_retry(
    chatgpt: Any,
    cs_id: str,
    checkout: dict[str, Any],
    max_attempts: int,
    progress: ProgressLogger = noop_progress,
    after_attempt: Callable[[int, int, str], str] | None = None,
) -> str:
    country = checkout["billing_country"]
    processor_entity = processor_entity_for_country(country, checkout.get("processor_entity", ""))
    attempts = normalize_approve_retries(max_attempts)
    try:
        progress("chatgpt_approve", "正在发送 sentinel ping，准备确认 checkout。", proxy_runtime_details(chatgpt))
        chatgpt.post(
            "https://chatgpt.com/backend-api/sentinel/ping",
            json={},
            headers={
                "Referer": "https://chatgpt.com/",
                "x-openai-target-path": "/backend-api/sentinel/ping",
                "x-openai-target-route": "/backend-api/sentinel/ping",
            },
            timeout=DEFAULT_TIMEOUT,
        )
    except Exception:
        pass
    progress("chatgpt_approve", f"Stripe 要求 ChatGPT 侧确认，开始对同一个 checkout 顺序 approve，最多 {attempts} 次。", {"cs_id": cs_id, "max_attempts": attempts, **proxy_runtime_details(chatgpt)})
    last_error = ""
    for attempt in range(1, attempts + 1):
        result = ""
        progress("chatgpt_approve", f"正在调用 checkout approve，第 {attempt}/{attempts} 次。", {"cs_id": cs_id, "approve_attempt": attempt, "approve_max_attempts": attempts})
        try:
            response = chatgpt.post(
                "https://chatgpt.com/backend-api/payments/checkout/approve",
                json={"checkout_session_id": cs_id, "processor_entity": processor_entity},
                headers={
                    "Referer": f"https://chatgpt.com/checkout/{processor_entity}/{cs_id}",
                    "x-openai-target-path": "/backend-api/payments/checkout/approve",
                    "x-openai-target-route": "/backend-api/payments/checkout/approve",
                },
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:
            last_error = f"request failed: {exc}"
        else:
            body_text = str(getattr(response, "text", "") or "")
            if response.status_code >= 400:
                last_error = f"http {response.status_code}: {body_text[:300]}"
            else:
                try:
                    result = str((response.json() or {}).get("result") or "").strip()
                except Exception:
                    result = ""
                if result == "approved":
                    progress("chatgpt_approve", f"ChatGPT checkout approve 已通过，第 {attempt}/{attempts} 次命中。", {"cs_id": cs_id, "approve_attempt": attempt, "approve_max_attempts": attempts, "result": result})
                    if after_attempt is not None:
                        redirect_url = after_attempt(attempt, attempts, result)
                        if redirect_url:
                            return redirect_url
                    return ""
                last_error = f"result={result!r} body={body_text[:300]}"
        progress("chatgpt_approve", f"checkout approve 第 {attempt}/{attempts} 次未通过。", {"cs_id": cs_id, "approve_attempt": attempt, "approve_max_attempts": attempts, "error": last_error})
        if after_attempt is not None:
            redirect_url = after_attempt(attempt, attempts, result)
            if redirect_url:
                return redirect_url
        if attempt < attempts:
            time.sleep(min(2.0, 0.4 + attempt * 0.2))
    raise HTTPException(status_code=502, detail=f"chatgpt approve 重试耗尽: {last_error}")


def redirect_url_after_confirm(
    chatgpt: Any,
    stripe: Any,
    confirm_payload: dict[str, Any],
    cs_id: str,
    stripe_pk: str,
    checkout: dict[str, Any],
    req: LongLinkRequest,
    ctx: dict[str, Any] | None = None,
    progress: ProgressLogger = noop_progress,
) -> str:
    ctx = ctx or {}
    terminal_error = extract_stripe_terminal_error(confirm_payload)
    if terminal_error:
        raise HTTPException(status_code=502, detail=terminal_error)
    redirect_url = extract_redirect_to_url(confirm_payload)
    if redirect_url:
        return redirect_url
    submission = confirm_payload.get("submission_attempt") if isinstance(confirm_payload, dict) else None
    if isinstance(submission, dict) and submission.get("state") == "requires_approval":
        checkout_proxy = checkout_stage_proxy(req)
        poll_proxy_switched = False

        def poll_redirect_after_approve(approve_attempt: int, approve_max_attempts: int, approve_result: str) -> str:
            nonlocal poll_proxy_switched
            if approve_result == "approved" and not poll_proxy_switched:
                if checkout_proxy:
                    set_proxy_url(stripe, checkout_proxy)
                else:
                    stripe.proxies = {}
                poll_proxy_switched = True
                progress("redirect_poll", "approve 已通过，Stripe redirect 轮询切回 checkout 代理。", proxy_runtime_details(stripe, checkout_proxy))
            progress("redirect_poll", f"approve 第 {approve_attempt}/{approve_max_attempts} 次后检查 Stripe redirect。", {"approve_attempt": approve_attempt, "approve_max_attempts": approve_max_attempts, "approve_result": approve_result})
            try:
                redirect_once = stripe_payment_page_redirect_url_once(stripe, cs_id, stripe_pk, req, ctx=ctx)
                if redirect_once:
                    return redirect_once
            except HTTPException as exc:
                if is_stripe_terminal_error_detail(exc.detail):
                    raise
                progress("redirect_poll", f"approve 第 {approve_attempt}/{approve_max_attempts} 次后暂未拿到 Stripe redirect，继续 approve。", {"error": str(exc.detail), "approve_attempt": approve_attempt})
                return ""
            except Exception as exc:
                progress("redirect_poll", f"approve 第 {approve_attempt}/{approve_max_attempts} 次后暂未拿到 Stripe redirect，继续 approve。", {"error": str(exc), "approve_attempt": approve_attempt})
                return ""
            if approve_result == "approved" or approve_attempt >= approve_max_attempts:
                try:
                    return stripe_payment_page_redirect_url(stripe, cs_id, stripe_pk, req, ctx=ctx, timeout_seconds=8, progress=progress)
                except HTTPException as exc:
                    if is_stripe_terminal_error_detail(exc.detail):
                        raise
                    progress("redirect_poll", f"approve 第 {approve_attempt}/{approve_max_attempts} 次后暂未拿到 Stripe redirect，继续 approve。", {"error": str(exc.detail), "approve_attempt": approve_attempt})
            return ""

        approved_redirect_url = chatgpt_approve_with_retry(
            chatgpt,
            cs_id,
            checkout,
            max_attempts=normalize_approve_retries(req.approve_retries),
            progress=progress,
            after_attempt=poll_redirect_after_approve,
        )
        if approved_redirect_url:
            return approved_redirect_url
        return stripe_payment_page_redirect_url(stripe, cs_id, stripe_pk, req, ctx=ctx, timeout_seconds=45, progress=progress)
    return stripe_payment_page_redirect_url(stripe, cs_id, stripe_pk, req, ctx=ctx, timeout_seconds=30, progress=progress)


def create_provider_link(
    chatgpt: Any,
    checkout: dict[str, Any],
    init_payload: dict[str, Any],
    stripe_hosted_url: str,
    req: LongLinkRequest,
    provider_proxy: str = "",
    stripe_session: Any | None = None,
    progress: ProgressLogger = noop_progress,
) -> dict[str, str]:
    link_type = normalize_link_type(req.link_type)
    stripe_pk = req.stripe_publishable_key.strip() or DEFAULT_STRIPE_PK
    stripe = stripe_session or build_stripe_session(req, proxy_override=provider_proxy)
    ctx = stripe_context(checkout["cs_id"], init_payload, req)
    hosted_long_url = to_openai_pay_url(stripe_hosted_url) or stripe_hosted_url
    billing = billing_for_link_type(link_type)
    pm_id = stripe_create_payment_method(stripe, checkout["cs_id"], stripe_pk, billing, link_type, ctx)
    confirm_payload = stripe_confirm(stripe, checkout["cs_id"], pm_id, stripe_pk, link_type, init_payload, ctx, checkout, req, stripe_hosted_url)
    preferred_hosts = ("paypal.com",) if link_type == "paypal" else ()
    try:
        stripe_redirect_url = redirect_url_after_confirm(chatgpt, stripe, confirm_payload, checkout["cs_id"], stripe_pk, checkout, req, ctx=ctx, progress=progress)
    except HTTPException as exc:
        if not is_stripe_terminal_error_detail(exc.detail) and hosted_long_url:
            progress("provider_recover", "Stripe poll 未拿到 redirect，尝试从 hosted 页面提取 provider 链接。", {"error": str(exc.detail)})
            provider_url = resolve_external_redirect(stripe, hosted_long_url, preferred_hosts=preferred_hosts)
            if not preferred_hosts or url_matches_hosts(provider_url, preferred_hosts):
                progress("provider_recover", "已从 hosted 页面提取到 provider 链接。", {"provider_redirect_url": provider_url})
                return {
                    "payment_method_id": pm_id,
                    "stripe_redirect_url": "",
                    "provider_redirect_url": provider_url,
                    "long_url": provider_url,
                }
        raise
    provider_url = resolve_external_redirect(stripe, stripe_redirect_url, preferred_hosts=preferred_hosts)
    if preferred_hosts and not url_matches_hosts(provider_url, preferred_hosts) and hosted_long_url:
        hosted_provider_url = resolve_external_redirect(stripe, hosted_long_url, preferred_hosts=preferred_hosts)
        if url_matches_hosts(hosted_provider_url, preferred_hosts):
            progress("provider_recover", "Stripe redirect 未直接落到 PayPal，已从 hosted 页面补提 provider 链接。", {"provider_redirect_url": hosted_provider_url})
            provider_url = hosted_provider_url
    return {
        "payment_method_id": pm_id,
        "stripe_redirect_url": stripe_redirect_url,
        "provider_redirect_url": provider_url,
        "long_url": provider_url or stripe_redirect_url,
    }


def stripe_payment_page_redirect_url_once(
    stripe: Any,
    cs_id: str,
    stripe_pk: str,
    req: LongLinkRequest,
    ctx: dict[str, Any] | None = None,
    raise_on_terminal: bool = True,
) -> str:
    response = stripe.get(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}",
        params=stripe_payment_page_params(stripe_pk, req, ctx),
        timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code != 200:
        return ""
    payload = response.json() or {}
    redirect_url = extract_redirect_to_url(payload)
    if redirect_url:
        return redirect_url
    terminal_error = extract_stripe_terminal_error(payload)
    if terminal_error:
        if raise_on_terminal:
            raise HTTPException(status_code=502, detail=terminal_error)
        return ""
    try:
        redirect_url = stripe_setup_intent_redirect_url_from_payload(stripe, payload, stripe_pk)
    except HTTPException:
        if raise_on_terminal:
            raise
        return ""
    if redirect_url:
        return redirect_url
    for candidate in extract_nested_redirect_urls(payload, ("paypal.com", "pm-redirects.stripe.com")):
        if is_actionable_stripe_redirect(candidate, ("paypal.com", "pm-redirects.stripe.com")):
            return candidate
    return ""


def stripe_payment_page_redirect_url(
    stripe: Any,
    cs_id: str,
    stripe_pk: str,
    req: LongLinkRequest,
    ctx: dict[str, Any] | None = None,
    timeout_seconds: float = 30,
    progress: ProgressLogger = noop_progress,
    raise_on_terminal: bool = True,
) -> str:
    deadline = time.time() + max(1.0, float(timeout_seconds or 30))
    last_err = ""
    params = stripe_payment_page_params(stripe_pk, req, ctx)
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        progress("redirect_poll", f"正在轮询 Stripe 跳转地址，第 {attempt} 次。")
        response = stripe.get(f"https://api.stripe.com/v1/payment_pages/{cs_id}", params=params, timeout=DEFAULT_TIMEOUT)
        if response.status_code == 200:
            payload = response.json() or {}
            redirect_url = extract_redirect_to_url(payload)
            if redirect_url:
                progress("redirect_poll", "已从 Stripe payment page 解析到跳转地址。")
                return redirect_url
            terminal_error = extract_stripe_terminal_error(payload)
            if terminal_error:
                if raise_on_terminal:
                    raise HTTPException(status_code=502, detail=terminal_error)
                last_err = terminal_error
            else:
                try:
                    redirect_url = stripe_setup_intent_redirect_url_from_payload(stripe, payload, stripe_pk)
                except HTTPException as exc:
                    if raise_on_terminal:
                        raise
                    last_err = str(exc.detail)
                    redirect_url = ""
                if redirect_url:
                    progress("redirect_poll", "已通过 SetupIntent 回查拿到跳转地址。")
                    return redirect_url
                for candidate in extract_nested_redirect_urls(payload, ("paypal.com", "pm-redirects.stripe.com")):
                    if is_actionable_stripe_redirect(candidate, ("paypal.com", "pm-redirects.stripe.com")):
                        progress("redirect_poll", "已从 payment page 深层字段解析到跳转地址。")
                        return candidate
                if not last_err:
                    last_err = f"keys=[{','.join(sorted(payload.keys())[:8])}]"
        else:
            last_err = f"http {response.status_code}: {response.text[:120]}"
        time.sleep(1)
    raise HTTPException(status_code=504, detail=f"redirect url resolution timeout: {last_err}")


def chatgpt_approve_once(chatgpt: Any, cs_id: str, checkout: dict[str, Any]) -> tuple[str, str]:
    country = checkout["billing_country"]
    processor_entity = processor_entity_for_country(country, checkout.get("processor_entity", ""))
    try:
        response = chatgpt.post(
            "https://chatgpt.com/backend-api/payments/checkout/approve",
            json={"checkout_session_id": cs_id, "processor_entity": processor_entity},
            headers={
                "Referer": f"https://chatgpt.com/checkout/{processor_entity}/{cs_id}",
                "x-openai-target-path": "/backend-api/payments/checkout/approve",
                "x-openai-target-route": "/backend-api/payments/checkout/approve",
            },
            timeout=DEFAULT_TIMEOUT,
        )
    except Exception as exc:
        return "", f"request failed: {exc}"
    body_text = str(getattr(response, "text", "") or "")
    if response.status_code >= 400:
        return "", f"http {response.status_code}: {body_text[:300]}"
    try:
        result = str((response.json() or {}).get("result") or "").strip()
    except Exception:
        result = ""
    if result:
        return result, ""
    return "", f"result={result!r} body={body_text[:300]}"


def probe_stripe_redirect_sources(
    stripe: Any,
    cs_id: str,
    stripe_pk: str,
    req: LongLinkRequest,
    ctx: dict[str, Any] | None = None,
    hosted_long_url: str = "",
    preferred_hosts: tuple[str, ...] = (),
    deep_scan: bool = False,
) -> str:
    preferred = preferred_hosts or ("paypal.com", "pm-redirects.stripe.com")
    redirect_url = stripe_payment_page_redirect_url_once(
        stripe, cs_id, stripe_pk, req, ctx=ctx, raise_on_terminal=False
    )
    if is_actionable_stripe_redirect(redirect_url, preferred):
        return redirect_url
    if hosted_long_url:
        hosted_redirect = fetch_hosted_redirect_candidates(stripe, hosted_long_url, preferred)
        if is_actionable_stripe_redirect(hosted_redirect, preferred):
            return hosted_redirect
    if deep_scan and redirect_url and is_actionable_stripe_redirect(redirect_url, preferred):
        return redirect_url
    return ""


def chatgpt_approve_concurrent_pool(
    chatgpt: Any,
    cs_id: str,
    checkout: dict[str, Any],
    *,
    pool_size: int,
    max_attempts: int,
    stripe: Any | None = None,
    stripe_pk: str = "",
    req: LongLinkRequest | None = None,
    ctx: dict[str, Any] | None = None,
    hosted_long_url: str = "",
    checkout_proxy: str = "",
    provider_proxy: str = "",
    confirm_payload: dict[str, Any] | None = None,
    pm_id: str = "",
    link_type: str = "paypal",
    init_payload: dict[str, Any] | None = None,
    checkout_payload: dict[str, Any] | None = None,
    stripe_hosted_url: str = "",
    progress: ProgressLogger = noop_progress,
) -> tuple[str, str]:
    pool_size = normalize_approve_pool_size(pool_size)
    max_attempts = normalize_approve_pool_max_attempts(max_attempts)
    stop_event = threading.Event()
    state_lock = threading.Lock()
    state: dict[str, Any] = {
        "redirect_url": "",
        "approve_result": "",
        "last_error": "",
        "attempts": 0,
        "approved_hits": 0,
        "blocked_hits": 0,
    }
    preferred_hosts = ("paypal.com", "pm-redirects.stripe.com")
    poll_ctx = ctx or {}
    poll_req = req or LongLinkRequest(accessToken="unused")
    poll_stripe_pk = stripe_pk or DEFAULT_STRIPE_PK
    poll_proxy_switched = False

    try:
        progress("chatgpt_approve", "正在发送 sentinel ping，准备确认 checkout。", proxy_runtime_details(chatgpt))
        chatgpt.post(
            "https://chatgpt.com/backend-api/sentinel/ping",
            json={},
            headers={
                "Referer": "https://chatgpt.com/",
                "x-openai-target-path": "/backend-api/sentinel/ping",
                "x-openai-target-route": "/backend-api/sentinel/ping",
            },
            timeout=DEFAULT_TIMEOUT,
        )
    except Exception:
        pass

    progress(
        "chatgpt_approve",
        f"ChatGPT Approve 并发请求池已启动：池容量 {pool_size} 路，最多 {max_attempts} 次。",
        {
            "cs_id": cs_id,
            "approve_pool_size": pool_size,
            "approve_pool_max_attempts": max_attempts,
            **proxy_runtime_details(chatgpt, checkout_proxy),
        },
    )

    def record_redirect(url: str, source: str) -> None:
        if not is_actionable_stripe_redirect(url, preferred_hosts):
            return
        with state_lock:
            if state["redirect_url"]:
                return
            state["redirect_url"] = url
        stop_event.set()
        progress("redirect_poll", f"并发轮询命中 Stripe/provider redirect（{source}）。", {"redirect_url": url})

    poll_proxy_cycle = stripe_poll_proxy_candidates(checkout_proxy, provider_proxy)

    def ensure_poll_proxy() -> Any | None:
        nonlocal poll_proxy_switched
        if stripe is None:
            return None
        with state_lock:
            approved = state["approve_result"] == "approved" or state["approved_hits"] > 0
            if approved and not poll_proxy_switched:
                poll_proxy = checkout_proxy or provider_proxy
                apply_poll_proxy(stripe, poll_proxy)
                poll_proxy_switched = True
                progress(
                    "redirect_poll",
                    "approve 已命中，Stripe redirect 轮询优先使用 checkout 代理。",
                    {
                        "approve_result": state["approve_result"],
                        "poll_proxy": safe_proxy_hint(poll_proxy),
                        **proxy_runtime_details(stripe, poll_proxy),
                    },
                )
        return stripe

    def redirect_poller_loop() -> None:
        if stripe is None:
            return
        cycle_index = 0
        while not stop_event.is_set():
            label, proxy = poll_proxy_cycle[cycle_index % len(poll_proxy_cycle)]
            cycle_index += 1
            active_clone = clone_http_session(stripe)
            apply_poll_proxy(active_clone, proxy)
            try:
                redirect_url = probe_stripe_redirect_sources(
                    active_clone,
                    cs_id,
                    poll_stripe_pk,
                    poll_req,
                    ctx=poll_ctx,
                    hosted_long_url=hosted_long_url,
                    preferred_hosts=preferred_hosts,
                    deep_scan=True,
                )
                if redirect_url:
                    record_redirect(redirect_url, f"payment_page_or_hosted:{label}")
                    return
            except Exception as exc:
                with state_lock:
                    state["last_error"] = str(exc)
            time.sleep(0.35)

    def approve_worker_loop() -> None:
        worker = clone_http_session(chatgpt)
        while not stop_event.is_set():
            with state_lock:
                if state["attempts"] >= max_attempts:
                    return
                state["attempts"] += 1
                attempt_no = state["attempts"]
            result, error_text = chatgpt_approve_once(worker, cs_id, checkout)
            with state_lock:
                if result == "approved":
                    state["approve_result"] = "approved"
                    state["approved_hits"] += 1
                elif result == "blocked":
                    state["blocked_hits"] += 1
                    if state["approve_result"] not in {"approved"}:
                        state["approve_result"] = "blocked"
                elif result and state["approve_result"] not in {"approved"}:
                    state["approve_result"] = result
                if error_text:
                    state["last_error"] = error_text
            if attempt_no == 1 or attempt_no % 25 == 0 or result == "approved":
                progress(
                    "chatgpt_approve",
                    f"并发 approve 第 {attempt_no}/{max_attempts} 次，approve_result={result or 'unknown'}。",
                    {
                        "cs_id": cs_id,
                        "approve_attempt": attempt_no,
                        "approve_max_attempts": max_attempts,
                        "approve_result": result or state["approve_result"] or "unknown",
                        "approve_pool_size": pool_size,
                        "blocked_hits": state["blocked_hits"],
                    },
                )
            if stripe is not None:
                active_stripe = ensure_poll_proxy() or stripe
                try:
                    poll_clone = clone_http_session(active_stripe)
                    apply_poll_proxy(poll_clone, checkout_proxy or provider_proxy)
                    redirect_url = probe_stripe_redirect_sources(
                        poll_clone,
                        cs_id,
                        poll_stripe_pk,
                        poll_req,
                        ctx=poll_ctx,
                        hosted_long_url=hosted_long_url,
                        preferred_hosts=preferred_hosts,
                        deep_scan=True,
                    )
                    if redirect_url:
                        record_redirect(redirect_url, "approve_worker")
                        return
                except Exception:
                    pass
            time.sleep(random.uniform(0.03, 0.15))

    worker_total = pool_size + (2 if stripe is not None else 0)
    deadline = time.time() + 120
    with ThreadPoolExecutor(max_workers=worker_total, thread_name_prefix="approve-pool") as executor:
        futures = [executor.submit(approve_worker_loop) for _ in range(pool_size)]
        if stripe is not None:
            futures.extend([executor.submit(redirect_poller_loop), executor.submit(redirect_poller_loop)])
        while time.time() < deadline and not stop_event.is_set():
            with state_lock:
                if state["redirect_url"]:
                    break
                attempts_used_now = int(state["attempts"] or 0)
            if attempts_used_now >= max_attempts and all(future.done() for future in futures):
                break
            time.sleep(0.2)
        stop_event.set()
        for future in futures:
            try:
                future.result(timeout=1)
            except Exception as exc:
                with state_lock:
                    state["last_error"] = str(exc)

    with state_lock:
        redirect_url = str(state["redirect_url"] or "")
        approve_result = str(state["approve_result"] or "")
        last_error = str(state["last_error"] or "")
        attempts_used = int(state["attempts"] or 0)
    if redirect_url and is_actionable_stripe_redirect(redirect_url, preferred_hosts):
        return redirect_url, approve_result
    redirect_url = ""
    if approve_result == "approved" and stripe is not None:
        recovered = post_approve_redirect_recovery(
            stripe,
            cs_id,
            poll_stripe_pk,
            poll_req,
            poll_ctx,
            hosted_long_url=hosted_long_url,
            checkout_proxy=checkout_proxy,
            provider_proxy=provider_proxy,
            timeout_seconds=45,
            progress=progress,
            confirm_payload=confirm_payload,
            pm_id=pm_id,
            link_type=link_type,
            init_payload=init_payload,
            checkout=checkout_payload,
            stripe_hosted_url=stripe_hosted_url,
        )
        if recovered and is_actionable_stripe_redirect(recovered, preferred_hosts):
            return recovered, approve_result
        try:
            recovered = stripe_payment_page_redirect_url(
                stripe,
                cs_id,
                poll_stripe_pk,
                poll_req,
                ctx=poll_ctx,
                timeout_seconds=30,
                progress=progress,
                raise_on_terminal=False,
            )
            if recovered and is_actionable_stripe_redirect(recovered, preferred_hosts):
                return recovered, approve_result
        except HTTPException:
            pass
    if approve_result == "approved":
        raise HTTPException(
            status_code=502,
            detail=f"chatgpt approve 已通过但未拿到 PayPal redirect: attempts={attempts_used}, last_error={last_error}; approve_result={approve_result!r}",
        )
    raise HTTPException(
        status_code=502,
        detail=f"chatgpt approve 并发池耗尽: attempts={attempts_used}, last_error={last_error}; approve_result={approve_result!r}",
    )


def chatgpt_approve_with_retry(
    chatgpt: Any,
    cs_id: str,
    checkout: dict[str, Any],
    max_attempts: int,
    progress: ProgressLogger = noop_progress,
    after_attempt: Callable[[int, int, str], str] | None = None,
    pool_size: int = 1,
    stripe: Any | None = None,
    stripe_pk: str = "",
    req: LongLinkRequest | None = None,
    ctx: dict[str, Any] | None = None,
    hosted_long_url: str = "",
    checkout_proxy: str = "",
    provider_proxy: str = "",
    confirm_payload: dict[str, Any] | None = None,
    pm_id: str = "",
    link_type: str = "paypal",
    init_payload: dict[str, Any] | None = None,
    checkout_payload: dict[str, Any] | None = None,
    stripe_hosted_url: str = "",
) -> tuple[str, str]:
    if after_attempt is not None:
        country = checkout["billing_country"]
        processor_entity = processor_entity_for_country(country, checkout.get("processor_entity", ""))
        attempts = normalize_approve_retries(max_attempts)
        try:
            progress("chatgpt_approve", "正在发送 sentinel ping，准备确认 checkout。", proxy_runtime_details(chatgpt))
            chatgpt.post(
                "https://chatgpt.com/backend-api/sentinel/ping",
                json={},
                headers={
                    "Referer": "https://chatgpt.com/",
                    "x-openai-target-path": "/backend-api/sentinel/ping",
                    "x-openai-target-route": "/backend-api/sentinel/ping",
                },
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception:
            pass
        progress(
            "chatgpt_approve",
            f"Stripe 要求 ChatGPT 侧确认，开始对同一个 checkout 顺序 approve，最多 {attempts} 次。",
            {"cs_id": cs_id, "max_attempts": attempts, **proxy_runtime_details(chatgpt)},
        )
        last_error = ""
        last_result = ""
        for attempt in range(1, attempts + 1):
            result, error_text = chatgpt_approve_once(chatgpt, cs_id, checkout)
            if error_text:
                last_error = error_text
            if result:
                last_result = result or last_result
            if result == "approved":
                progress(
                    "chatgpt_approve",
                    f'ChatGPT checkout approve 已通过，approve_result="{result}"，第 {attempt}/{attempts} 次命中。',
                    {
                        "cs_id": cs_id,
                        "approve_attempt": attempt,
                        "approve_max_attempts": attempts,
                        "approve_result": result,
                    },
                )
                redirect_url = after_attempt(attempt, attempts, result)
                if redirect_url:
                    return redirect_url, result
                return "", result
            progress(
                "chatgpt_approve",
                f'checkout approve 第 {attempt}/{attempts} 次未通过，approve_result="{result or "unknown"}"。',
                {
                    "cs_id": cs_id,
                    "approve_attempt": attempt,
                    "approve_max_attempts": attempts,
                    "approve_result": result or "unknown",
                    "error": last_error,
                },
            )
            redirect_url = after_attempt(attempt, attempts, result)
            if redirect_url:
                return redirect_url, result or last_result
            if attempt < attempts:
                time.sleep(min(2.0, 0.4 + attempt * 0.2))
        raise HTTPException(status_code=502, detail=f"chatgpt approve 重试耗尽: {last_error}; approve_result={last_result!r}")

    effective_pool_size = normalize_approve_pool_size(pool_size)
    effective_max_attempts = normalize_approve_pool_max_attempts(max_attempts)
    serial_cap = normalize_approve_retries(max_attempts)
    if effective_max_attempts <= serial_cap:
        effective_max_attempts = max(effective_max_attempts, serial_cap)
    if effective_pool_size <= 1 and stripe is None and effective_max_attempts <= 30:
        last_error = ""
        last_result = ""
        for attempt in range(1, effective_max_attempts + 1):
            result, error_text = chatgpt_approve_once(chatgpt, cs_id, checkout)
            if error_text:
                last_error = error_text
            if result:
                last_result = result or last_result
            if result == "approved":
                progress(
                    "chatgpt_approve",
                    f'ChatGPT checkout approve 已通过，approve_result="{result}"，第 {attempt}/{effective_max_attempts} 次命中。',
                    {
                        "cs_id": cs_id,
                        "approve_attempt": attempt,
                        "approve_max_attempts": effective_max_attempts,
                        "approve_result": result,
                    },
                )
                return "", result
            progress(
                "chatgpt_approve",
                f'checkout approve 第 {attempt}/{effective_max_attempts} 次未通过，approve_result="{result or "unknown"}"。',
                {
                    "cs_id": cs_id,
                    "approve_attempt": attempt,
                    "approve_max_attempts": effective_max_attempts,
                    "approve_result": result or "unknown",
                    "error": last_error,
                },
            )
            if attempt < effective_max_attempts:
                time.sleep(min(2.0, 0.4 + attempt * 0.2))
        raise HTTPException(
            status_code=502,
            detail=f"chatgpt approve 重试耗尽: {last_error}; approve_result={last_result!r}",
        )
    return chatgpt_approve_concurrent_pool(
        chatgpt,
        cs_id,
        checkout,
        pool_size=effective_pool_size,
        max_attempts=effective_max_attempts,
        stripe=stripe,
        stripe_pk=stripe_pk,
        req=req,
        ctx=ctx,
        hosted_long_url=hosted_long_url,
        checkout_proxy=checkout_proxy,
        provider_proxy=provider_proxy,
        confirm_payload=confirm_payload,
        pm_id=pm_id,
        link_type=link_type,
        init_payload=init_payload,
        checkout_payload=checkout_payload,
        stripe_hosted_url=stripe_hosted_url,
        progress=progress,
    )


def redirect_url_after_confirm(
    chatgpt: Any,
    stripe: Any,
    confirm_payload: dict[str, Any],
    cs_id: str,
    stripe_pk: str,
    checkout: dict[str, Any],
    req: LongLinkRequest,
    ctx: dict[str, Any] | None = None,
    progress: ProgressLogger = noop_progress,
    hosted_long_url: str = "",
    pm_id: str = "",
    init_payload: dict[str, Any] | None = None,
    stripe_hosted_url: str = "",
) -> tuple[str, str]:
    ctx = ctx or {}
    terminal_error = extract_stripe_terminal_error(confirm_payload)
    if terminal_error:
        raise HTTPException(status_code=502, detail=terminal_error)
    redirect_url = extract_redirect_to_url(confirm_payload)
    if redirect_url:
        return redirect_url, ""
    submission = confirm_payload.get("submission_attempt") if isinstance(confirm_payload, dict) else None
    if isinstance(submission, dict) and submission.get("state") == "requires_approval":
        checkout_proxy = checkout_stage_proxy(req)
        provider_proxy = provider_stage_proxy(req)
        if checkout_proxy:
            set_proxy_url(chatgpt, checkout_proxy)
        else:
            chatgpt.proxies = {}
        progress(
            "chatgpt_approve",
            "requires_approval：ChatGPT approve 已切回 checkout 代理，启动并发 approve 池。",
            {
                "approve_result": "pending",
                "approve_pool_size": normalize_approve_pool_size(req.approve_pool_size),
                "approve_pool_max_attempts": normalize_approve_pool_max_attempts(req.approve_pool_max_attempts),
                "provider_proxy": safe_proxy_hint(provider_proxy),
                **proxy_runtime_details(chatgpt, checkout_proxy),
            },
        )
        pool_max_attempts = normalize_approve_pool_max_attempts(req.approve_pool_max_attempts)
        if pool_max_attempts <= normalize_approve_retries(req.approve_retries):
            pool_max_attempts = max(pool_max_attempts, normalize_approve_retries(req.approve_retries))
        approved_redirect_url, approve_result = chatgpt_approve_with_retry(
            chatgpt,
            cs_id,
            checkout,
            max_attempts=pool_max_attempts,
            progress=progress,
            pool_size=normalize_approve_pool_size(req.approve_pool_size),
            stripe=stripe,
            stripe_pk=stripe_pk,
            req=req,
            ctx=ctx,
            hosted_long_url=hosted_long_url,
            checkout_proxy=checkout_proxy,
            provider_proxy=provider_proxy,
            confirm_payload=confirm_payload,
            pm_id=pm_id,
            link_type=normalize_link_type(req.link_type),
            init_payload=init_payload,
            checkout_payload=checkout,
            stripe_hosted_url=stripe_hosted_url,
        )
        if approved_redirect_url:
            return approved_redirect_url, approve_result
        if approve_result == "approved":
            try:
                recovered = stripe_payment_page_redirect_url(
                    stripe,
                    cs_id,
                    stripe_pk,
                    req,
                    ctx=ctx,
                    timeout_seconds=30,
                    progress=progress,
                    raise_on_terminal=False,
                )
                if recovered:
                    return recovered, approve_result
            except HTTPException:
                pass
            recovered = post_approve_redirect_recovery(
                stripe,
                cs_id,
                stripe_pk,
                req,
                ctx,
                hosted_long_url=hosted_long_url,
                checkout_proxy=checkout_proxy,
                provider_proxy=provider_proxy,
                timeout_seconds=45,
                progress=progress,
                confirm_payload=confirm_payload,
                pm_id=pm_id,
                link_type=normalize_link_type(req.link_type),
                init_payload=init_payload,
                checkout=checkout,
                stripe_hosted_url=stripe_hosted_url,
            )
            if recovered:
                return recovered, approve_result
        return (
            stripe_payment_page_redirect_url(
                stripe,
                cs_id,
                stripe_pk,
                req,
                ctx=ctx,
                timeout_seconds=45,
                progress=progress,
                raise_on_terminal=False,
            ),
            approve_result,
        )
    return stripe_payment_page_redirect_url(stripe, cs_id, stripe_pk, req, ctx=ctx, timeout_seconds=30, progress=progress), ""


def create_provider_link(
    chatgpt: Any,
    checkout: dict[str, Any],
    init_payload: dict[str, Any],
    stripe_hosted_url: str,
    req: LongLinkRequest,
    provider_proxy: str = "",
    stripe_session: Any | None = None,
    progress: ProgressLogger = noop_progress,
) -> dict[str, str]:
    link_type = normalize_link_type(req.link_type)
    stripe_pk = req.stripe_publishable_key.strip() or DEFAULT_STRIPE_PK
    stripe = stripe_session or build_stripe_session(req, proxy_override=provider_proxy)
    ctx = stripe_context(checkout["cs_id"], init_payload, req)
    hosted_long_url = to_openai_pay_url(stripe_hosted_url) or stripe_hosted_url
    billing = billing_for_link_type(link_type, checkout.get("billing_country", "US"))
    session_email = extract_session_email(req.access_token)
    if session_email:
        billing["email"] = session_email
    progress(
        "provider_prepare",
        f"已生成 provider 账单资料：{checkout.get('billing_country', 'US')} / {checkout.get('currency', '')} / {link_type}",
        {"billing_country": billing.get("country"), "currency": checkout.get("currency"), "payment_method_type": link_type},
    )
    pm_id = stripe_create_payment_method(stripe, checkout["cs_id"], stripe_pk, billing, link_type, ctx)
    confirm_payload = stripe_confirm(stripe, checkout["cs_id"], pm_id, stripe_pk, link_type, init_payload, ctx, checkout, req, stripe_hosted_url)
    preferred_hosts = ("paypal.com",) if link_type == "paypal" else ()
    approve_result = ""
    try:
        stripe_redirect_url, approve_result = redirect_url_after_confirm(
            chatgpt,
            stripe,
            confirm_payload,
            checkout["cs_id"],
            stripe_pk,
            checkout,
            req,
            ctx=ctx,
            progress=progress,
            hosted_long_url=hosted_long_url,
            pm_id=pm_id,
            init_payload=init_payload,
            stripe_hosted_url=stripe_hosted_url,
        )
        if not stripe_redirect_url and approve_result == "approved":
            stripe_redirect_url = stripe_finalize_after_approve(
                stripe,
                checkout["cs_id"],
                pm_id,
                stripe_pk,
                link_type,
                init_payload,
                ctx,
                checkout,
                req,
                stripe_hosted_url,
                confirm_payload=confirm_payload,
                progress=progress,
            )
    except HTTPException as exc:
        if not is_stripe_terminal_error_detail(exc.detail) and hosted_long_url:
            progress("provider_recover", "Stripe poll 未拿到 redirect，尝试从 hosted 页面提取 provider 链接。", {"error": str(exc.detail)})
            provider_url = resolve_external_redirect(stripe, hosted_long_url, preferred_hosts=preferred_hosts)
            if not preferred_hosts or url_matches_hosts(provider_url, preferred_hosts):
                progress("provider_recover", "已从 hosted 页面提取到 provider 链接。", {"provider_redirect_url": provider_url})
                return {
                    "payment_method_id": pm_id,
                    "stripe_redirect_url": "",
                    "provider_redirect_url": provider_url,
                    "long_url": provider_url,
                    "approve_result": approve_result,
                }
        raise
    provider_url = resolve_external_redirect(stripe, stripe_redirect_url, preferred_hosts=preferred_hosts)
    if preferred_hosts and not url_matches_hosts(provider_url, preferred_hosts):
        try:
            repoll_url = stripe_payment_page_redirect_url(
                stripe,
                checkout["cs_id"],
                stripe_pk,
                req,
                ctx=ctx,
                timeout_seconds=45 if approve_result == "approved" else 20,
                progress=progress,
                raise_on_terminal=False,
            )
            if is_actionable_stripe_redirect(repoll_url, preferred_hosts):
                stripe_redirect_url = repoll_url
                provider_url = resolve_external_redirect(stripe, repoll_url, preferred_hosts=preferred_hosts)
        except HTTPException:
            pass
    if preferred_hosts and not url_matches_hosts(provider_url, preferred_hosts) and hosted_long_url:
        hosted_provider_url = resolve_external_redirect(stripe, hosted_long_url, preferred_hosts=preferred_hosts)
        if url_matches_hosts(hosted_provider_url, preferred_hosts):
            progress("provider_recover", "Stripe redirect 未直接落到 PayPal，已从 hosted 页面补提 provider 链接。", {"provider_redirect_url": hosted_provider_url})
            provider_url = hosted_provider_url
    long_url = provider_url or stripe_redirect_url
    if link_type == "paypal":
        progress(
            "provider_redirect",
            f"{checkout['cs_id']} : {checkout.get('billing_country', '')} - {checkout.get('currency', '')} - paypal",
            {
                "cs_id": checkout["cs_id"],
                "billing_country": checkout.get("billing_country"),
                "currency": checkout.get("currency"),
                "long_url": long_url,
                "is_paypal_ba": "paypal.com/agreements/approve" in str(long_url or ""),
            },
        )
    return {
        "payment_method_id": pm_id,
        "stripe_redirect_url": stripe_redirect_url,
        "provider_redirect_url": provider_url,
        "long_url": long_url,
        "approve_result": approve_result,
    }


def is_paypal_ba_url(url: str) -> bool:
    return "paypal.com/agreements/approve" in str(url or "")


def is_actionable_stripe_redirect(url: str, preferred_hosts: tuple[str, ...] = ()) -> bool:
    current = str(url or "").strip()
    if not current:
        return False
    if url_matches_hosts(current, preferred_hosts):
        return True
    host = (urlsplit(current).netloc or "").lower()
    if host.endswith("pm-redirects.stripe.com") or host.endswith("hooks.stripe.com"):
        return True
    if host.endswith("paypal.com"):
        return True
    if host.endswith("stripe.com") and "/payments/checkout" in current:
        return False
    return bool(re.search(r"pm-redirects\.stripe\.com|hooks\.stripe\.com|paypal\.com", current, re.I))


app = FastAPI(title="OpenAI Pay Long Link")
app.mount("/public", StaticFiles(directory=PUBLIC_DIR), name="public")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/api/long-link", response_model=LongLinkResponse)
def generate_long_link(req: LongLinkRequest) -> LongLinkResponse:
    return generate_long_link_core(req)


def generate_long_link_once(req: LongLinkRequest, progress: ProgressLogger = noop_progress) -> LongLinkResponse:
    req = apply_payment_strategy(req)
    link_type = normalize_link_type(req.link_type)
    checkout_proxy = checkout_stage_proxy(req)
    provider_proxy = provider_stage_proxy(req) if link_type in {"paypal", "gopay"} else ""
    progress(
        "input",
        "input",
        {
            "link_type": link_type,
            "payment_strategy": normalize_payment_strategy(req.payment_strategy),
            "billing_country": effective_country(req),
            "currency": currency_for_country(effective_country(req)),
            "token": safe_token_hint(req.access_token),
            "checkout_proxy": safe_proxy_hint(checkout_proxy),
            "provider_proxy": safe_proxy_hint(provider_proxy) if provider_proxy else "",
            "stripe_timezone": stripe_timezone_for_req(req),
        },
    )
    progress("chatgpt_session", "chatgpt_session")
    chatgpt = build_chatgpt_session(req)
    progress("chatgpt_session", "chatgpt_session", proxy_runtime_details(chatgpt, checkout_proxy))
    progress("checkout", "checkout")
    checkout = create_checkout(req, chatgpt)
    progress(
        "checkout",
        "checkout 创建成功",
        {
            "cs_id": checkout["cs_id"],
            "billing_country": checkout["billing_country"],
            "currency": checkout["currency"],
            "processor_entity": checkout["processor_entity"],
        },
    )
    post_checkout_proxy = ""
    stripe_init_proxy = ""
    provider_stripe = None
    if link_type in {"paypal", "gopay"}:
        stripe_init_proxy = checkout_proxy
        post_checkout_proxy = provider_proxy
        provider_stripe = build_stripe_session(req, proxy_override=stripe_init_proxy)
    if link_type in {"paypal", "gopay"}:
        time.sleep(1.2)
    progress("stripe_init", "stripe_init")
    init_payload = stripe_init(checkout["cs_id"], req, proxy_override=stripe_init_proxy, stripe_session=provider_stripe)
    stripe_hosted_url = str(init_payload.get("stripe_hosted_url") or "").strip()
    if not stripe_hosted_url:
        raise HTTPException(status_code=502, detail=f"stripe init response missing stripe_hosted_url, keys={sorted(init_payload.keys())}")
    progress(
        "stripe_init",
        "stripe_init",
        {
            "stripe_hosted_url": stripe_hosted_url,
            **(init_payload.get("_runtime_proxy") if isinstance(init_payload.get("_runtime_proxy"), dict) else {}),
        },
    )
    hosted_long_url = to_openai_pay_url(stripe_hosted_url)
    progress("hosted_url", "hosted_url", {"hosted_long_url": hosted_long_url})
    if link_type in {"paypal", "gopay"} and provider_stripe is not None:
        if post_checkout_proxy:
            set_proxy_url(provider_stripe, post_checkout_proxy)
        else:
            provider_stripe.proxies = {}
        progress(
            "provider_proxy",
            "provider_proxy",
            {
                "proxy": safe_proxy_hint(post_checkout_proxy),
                "configured_protocol": str(urlsplit(post_checkout_proxy).scheme or "direct"),
                **proxy_runtime_details(provider_stripe, post_checkout_proxy),
            },
        )
    provider = {
        "payment_method_id": "",
        "stripe_redirect_url": "",
        "provider_redirect_url": "",
        "long_url": hosted_long_url,
        "approve_result": "",
    }
    fallback = False
    provider_error = ""
    if link_type in {"paypal", "gopay"}:
        try:
            provider = create_provider_link(
                chatgpt,
                checkout,
                init_payload,
                stripe_hosted_url,
                req,
                provider_proxy=post_checkout_proxy,
                stripe_session=provider_stripe,
                progress=progress,
            )
        except HTTPException as exc:
            fallback = True
            provider_error = str(exc.detail)
            progress("fallback", "fallback", {"error": provider_error})
        except Exception as exc:
            fallback = True
            provider_error = str(exc)
            progress("fallback", "fallback", {"error": provider_error})
        if link_type == "paypal" and not fallback:
            long_url = str(provider.get("long_url") or "")
            if not is_paypal_ba_url(long_url):
                fallback = True
                provider_error = f"PAYPAL_LINK_NOT_FOUND: 当前仅拿到 {long_url[:200]}"
                provider["long_url"] = hosted_long_url
                progress("fallback", "未拿到 PayPal BA 链，将按失败重试。", {"error": provider_error, "long_url": long_url})
    return response_from_parts(req, link_type, checkout, stripe_hosted_url, hosted_long_url, provider, fallback, provider_error, ok=not fallback)


def generate_long_link_core(req: LongLinkRequest, progress: ProgressLogger = noop_progress) -> LongLinkResponse:
    link_type = normalize_link_type(req.link_type)
    max_attempts = 1 if link_type == "hosted" else normalize_max_retries(req.max_retries)
    retry_history: list[RetryHistoryItem] = []
    last_result: LongLinkResponse | None = None
    for attempt in range(1, max_attempts + 1):
        def attempt_progress(step: str, message: str, data: dict[str, Any] | None = None) -> None:
            payload = dict(data or {})
            payload.setdefault("attempt", attempt)
            payload.setdefault("max_attempts", max_attempts)
            if step == "input":
                payload.setdefault("reset_steps", True)
            progress(step, message, payload)
        progress("retry", "retry", {"attempt": attempt, "max_attempts": max_attempts, "phase": "attempt_start"})
        try:
            result = generate_long_link_once(req, progress=attempt_progress)
        except HTTPException as exc:
            error_text = str(exc.detail)
            retry_history.append(RetryHistoryItem(attempt=attempt, ok=False, error=error_text))
            if attempt < max_attempts:
                progress("retry", "retry", {"attempt": attempt, "max_attempts": max_attempts, "error": error_text, "phase": "attempt_failed", "will_retry": True})
                continue
            raise
        except Exception as exc:
            error_text = str(exc)
            retry_history.append(RetryHistoryItem(attempt=attempt, ok=False, error=error_text))
            if attempt < max_attempts:
                progress("retry", "retry", {"attempt": attempt, "max_attempts": max_attempts, "error": error_text, "phase": "attempt_failed", "will_retry": True})
                continue
            raise
        last_result = result
        if link_type in {"paypal", "gopay"} and result.fallback:
            error_text = result.provider_error or "provider fallback"
            retry_history.append(RetryHistoryItem(attempt=attempt, ok=False, error=error_text, fallback=True, long_url=result.long_url))
            will_retry = attempt < max_attempts
            progress("fallback", "fallback", {"attempt": attempt, "max_attempts": max_attempts, "error": error_text, "phase": "attempt_failed", "will_retry": will_retry, "fallback_long_url": result.long_url})
            if will_retry:
                progress("retry", "retry", {"attempt": attempt, "max_attempts": max_attempts, "error": error_text, "phase": "attempt_failed", "will_retry": True})
                continue
            final_result = result.model_copy(update={"ok": False, "attempt_count": attempt, "max_attempts": max_attempts, "retry_history": list(retry_history)})
            progress("done", "生成流程完成", {"attempt": attempt, "max_attempts": max_attempts, "long_url": final_result.long_url, "fallback": final_result.fallback, "provider_error": final_result.provider_error})
            return final_result
        retry_history.append(RetryHistoryItem(attempt=attempt, ok=True, long_url=result.long_url))
        final_result = result.model_copy(update={"ok": True, "attempt_count": attempt, "max_attempts": max_attempts, "retry_history": list(retry_history)})
        progress("done", "生成流程完成", {"attempt": attempt, "max_attempts": max_attempts, "long_url": final_result.long_url, "fallback": final_result.fallback, "provider_error": final_result.provider_error})
        return final_result
    if last_result is not None:
        return last_result
    raise HTTPException(status_code=500, detail="generate failed")


def stream_event(event: str, payload: dict[str, Any]) -> str:
    return json.dumps({"event": event, **payload}, ensure_ascii=False) + "\n"


@app.post("/api/long-link/stream")
def generate_long_link_stream(req: LongLinkRequest) -> StreamingResponse:
    events: queue.Queue[dict[str, Any] | None] = queue.Queue()
    task_id = normalize_task_id(req.task_id) or uuid.uuid4().hex
    pause_controller = get_or_create_task_controller(task_id)

    def progress(step: str, message: str, data: dict[str, Any] | None = None) -> None:
        pause_controller.raise_if_cancelled()
        if pause_controller.wait_if_paused():
            events.put({"type": "log", "step": "pause", "message": "pause", "data": {"task_id": task_id}, "ts": time.strftime("%H:%M:%S")})
        pause_controller.raise_if_cancelled()
        events.put({"type": "log", "step": step, "message": message, "data": data or {}, "ts": time.strftime("%H:%M:%S")})

    def worker() -> None:
        try:
            result = generate_long_link_core(req, progress=progress)
            events.put({"type": "result", "data": result.model_dump(by_alias=True)})
        except TaskCancelled as exc:
            events.put({"type": "cancelled", "status_code": 499, "step": "terminate", "message": str(exc), "data": {"task_id": task_id}, "ts": time.strftime("%H:%M:%S")})
        except HTTPException as exc:
            events.put({"type": "error", "status_code": exc.status_code, "message": str(exc.detail), "ts": time.strftime("%H:%M:%S")})
        except Exception as exc:
            events.put({"type": "error", "status_code": 500, "message": str(exc), "ts": time.strftime("%H:%M:%S")})
        finally:
            release_task_controller(task_id)
            events.put(None)

    def event_stream() -> Iterator[str]:
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        yield stream_event("log", {"type": "log", "step": "start", "message": "start", "data": {}, "ts": time.strftime("%H:%M:%S")})
        while True:
            item = events.get()
            if item is None:
                break
            yield stream_event(str(item.get("type") or "log"), item)

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@app.post("/api/check-proxy", response_model=ProxyCheckResponse)
def check_proxy(req: ProxyCheckRequest) -> ProxyCheckResponse:
    return build_proxy_check_response(req)


@app.post("/api/plus/payment-link/check-proxy")
def check_payment_link_proxy(req: ProxyCheckRequest) -> dict[str, Any]:
    response = build_proxy_check_response(req)
    first_ok = next((item for item in response.checks if item.ok), None)
    if not first_ok:
        raise HTTPException(status_code=400, detail=response.message)
    return {"success": True, "proxy_info": legacy_proxy_info(first_ok), "checks": [item.model_dump() for item in response.checks]}


@app.post("/getPayPal_link", response_model=PublicPayPalLinkResponse)
def get_paypal_link(req: PublicPayPalLinkRequest) -> PublicPayPalLinkResponse:
    raw_input = resolve_public_paypal_input(req)
    max_attempts = normalize_max_retries(req.max_retries)
    if not normalize_access_token(raw_input):
        return PublicPayPalLinkResponse(
            success=False,
            code="INVALID_INPUT",
            message="invalid",
            paypal_link="",
            hosted_long_url="",
            attempt_count=0,
            max_attempts=max_attempts,
            retries_used=0,
            cs_id="",
            billing_country="",
            currency="",
            provider_error="",
            last_error="",
            provider_redirect_url="",
            stripe_redirect_url="",
            stripe_hosted_url="",
            retry_history=[],
        )
    runtime_retry_history: list[RetryHistoryItem] = []
    runtime_attempt = 0
    runtime_max_attempts = max_attempts

    def progress(_step: str, _message: str, data: dict[str, Any] | None = None) -> None:
        nonlocal runtime_attempt, runtime_max_attempts
        payload = dict(data or {})
        attempt = int(payload.get("attempt") or 0)
        max_value = int(payload.get("max_attempts") or runtime_max_attempts or max_attempts)
        if attempt > runtime_attempt:
            runtime_attempt = attempt
        runtime_max_attempts = max(1, max_value)
        if payload.get("phase") != "attempt_failed":
            return
        error_text = str(payload.get("error") or "").strip()
        if not attempt or not error_text:
            return
        if runtime_retry_history and runtime_retry_history[-1].attempt == attempt and runtime_retry_history[-1].error == error_text:
            return
        runtime_retry_history.append(RetryHistoryItem(attempt=attempt, ok=False, error=error_text))

    inner_req = build_public_paypal_request(req)
    try:
        result = generate_long_link_core(inner_req, progress=progress)
        if result.long_url and "paypal.com/agreements/approve" in result.long_url:
            return build_public_paypal_success(result)
        return PublicPayPalLinkResponse(
            success=False,
            code="PAYPAL_LINK_NOT_FOUND",
            message=result.provider_error or "not found",
            paypal_link="",
            hosted_long_url=result.long_url,
            attempt_count=result.attempt_count,
            max_attempts=result.max_attempts,
            retries_used=max(0, result.attempt_count - 1),
            cs_id=result.cs_id,
            billing_country=result.billing_country,
            currency=result.currency,
            provider_error=result.provider_error,
            last_error=result.provider_error,
            provider_redirect_url=result.provider_redirect_url,
            stripe_redirect_url=result.stripe_redirect_url,
            stripe_hosted_url=result.stripe_hosted_url,
            retry_history=result.retry_history,
        )
    except HTTPException as exc:
        attempt_count = runtime_attempt or runtime_max_attempts
        failure = build_public_paypal_failure(str(exc.detail), attempt_count, runtime_max_attempts, runtime_retry_history)
        failure.code = "UPSTREAM_ERROR"
        return failure
    except Exception as exc:
        attempt_count = runtime_attempt or runtime_max_attempts
        failure = build_public_paypal_failure(str(exc), attempt_count, runtime_max_attempts, runtime_retry_history)
        failure.code = "UPSTREAM_ERROR"
        return failure


# 这里用干净定义覆盖前面被错误编码污染的代理检测文案，不改变检测逻辑本身。
def check_proxy_info(proxy_url: str = "") -> dict[str, Any]:
    endpoints = [
        "http://ip-api.com/json?fields=status,message,query,country,countryCode,regionName,city,timezone,org,isp",
        "https://ipinfo.io/json",
    ]
    errors: list[str] = []
    for candidate in proxy_candidates(normalize_proxy_url(proxy_url)):
        for url in endpoints:
            try:
                proxies = {"http": candidate, "https": candidate} if candidate else None
                response = requests.get(url, proxies=proxies, timeout=8)
                response.raise_for_status()
            except Exception as exc:
                errors.append(f"{mask_proxy_url(candidate) or 'direct'} -> {url}: {exc}")
                if CurlCffiSession is None:
                    continue
                try:
                    probe = new_session()
                    probe.headers.update(
                        {
                            "User-Agent": DEFAULT_USER_AGENT,
                            "Accept-Language": "en-US,en;q=0.9",
                        }
                    )
                    if candidate:
                        set_proxy_url(probe, candidate)
                    response = probe.get(url, timeout=8)
                    if hasattr(response, "raise_for_status"):
                        response.raise_for_status()
                except Exception as fallback_exc:
                    errors.append(f"{mask_proxy_url(candidate) or 'direct'} -> {url} [session]: {fallback_exc}")
                    continue
            info = normalize_proxy_probe_payload(response.json() or {})
            if not info.get("ip"):
                raise RuntimeError("代理检测结果缺少 IP")
            info["proxy"] = mask_proxy_url(candidate) if candidate else "direct"
            info["proxy_url"] = candidate
            info["protocol"] = urlsplit(candidate).scheme if candidate else "direct"
            info["source"] = urlsplit(url).netloc
            return info
    raise RuntimeError("代理检测失败: " + "; ".join(errors[-3:]))


def build_proxy_check_response(req: ProxyCheckRequest) -> ProxyCheckResponse:
    link_type = normalize_link_type(req.link_type)
    stage = str(req.stage or "").strip().lower()
    checks: list[ProxyCheckItem] = []
    checkout_proxy = checkout_stage_proxy(req)
    provider_proxy = provider_stage_proxy(req) if link_type in {"paypal", "gopay"} else ""
    checkout_kind = "custom" if (req.checkout_proxy or req.proxy_input or req.proxy) else "builtin"
    checkout_source = "请求代理输入" if checkout_kind == "custom" else "内置 checkout 代理"
    provider_kind = "custom" if req.provider_proxy else "builtin"
    provider_source = "前端自定义 provider 代理" if provider_kind == "custom" else "内置 provider（随账单地区切换）代理"
    if stage == "provider":
        checks.append(proxy_check_item("provider", "provider 阶段", provider_proxy, provider_kind, provider_source))
    elif stage == "checkout":
        checks.append(proxy_check_item("checkout", "checkout 阶段", checkout_proxy, checkout_kind, checkout_source))
    else:
        checks.append(proxy_check_item("checkout", "checkout 阶段", checkout_proxy, checkout_kind, checkout_source))
        if link_type in {"paypal", "gopay"}:
            checks.append(proxy_check_item("provider", "provider 阶段", provider_proxy, provider_kind, provider_source))
    ok = all(item.ok for item in checks)
    return ProxyCheckResponse(ok=ok, message="代理检测完成" if ok else "代理检测失败", checks=checks)


@app.post("/api/long-link/tasks/{task_id}/pause")
def pause_long_link_task(task_id: str) -> dict[str, Any]:
    controller = get_or_create_task_controller(task_id)
    controller.pause()
    return {"ok": True, "task_id": normalize_task_id(task_id), "paused": controller.is_paused()}


@app.post("/api/long-link/tasks/{task_id}/resume")
def resume_long_link_task(task_id: str) -> dict[str, Any]:
    controller = get_or_create_task_controller(task_id)
    controller.resume()
    return {"ok": True, "task_id": normalize_task_id(task_id), "paused": controller.is_paused()}


def set_task_pause_state(task_id: str, paused: bool) -> dict[str, Any]:
    controller = get_or_create_task_controller(task_id)
    if paused:
        controller.pause()
    else:
        controller.resume()
    return {"ok": True, "task_id": normalize_task_id(task_id), "paused": controller.is_paused()}


def terminate_task(task_id: str) -> dict[str, Any]:
    controller = get_or_create_task_controller(task_id)
    controller.cancel()
    return {"ok": True, "task_id": normalize_task_id(task_id), "cancelled": controller.is_cancelled()}


@app.post("/api/long-link/tasks/{task_id}/terminate")
def terminate_long_link_task(task_id: str) -> dict[str, Any]:
    return terminate_task(task_id)


@app.post("/api/long-link/tasks/{task_id}/cancel")
def cancel_long_link_task(task_id: str) -> dict[str, Any]:
    return terminate_task(task_id)
