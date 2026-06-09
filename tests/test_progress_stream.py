import json
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import requests

import app


class FakeProxyResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, str]:
        return {
            "status": "success",
            "query": "125.103.37.73",
            "country": "Japan",
            "countryCode": "JP",
            "regionName": "Fukuoka",
            "city": "Fuke",
            "isp": "broadgate-un",
            "org": "broadgate-un",
        }


class FakeApproveResponse:
    def __init__(self, result: str, status_code: int = 200) -> None:
        self.status_code = status_code
        self.text = json.dumps({"result": result}, ensure_ascii=False)
        self._result = result

    def json(self) -> dict[str, str]:
        return {"result": self._result}


class FakeHttpResponse:
    def __init__(self, status_code: int = 200, text: str = "", json_data=None, headers=None, url: str = "") -> None:
        self.status_code = status_code
        self.text = text
        self._json_data = {} if json_data is None else json_data
        self.headers = {} if headers is None else headers
        self.url = url

    def json(self):
        return self._json_data


class ProgressStreamTests(unittest.TestCase):
    def make_request(self) -> app.LongLinkRequest:
        return app.LongLinkRequest(
            accessToken='{"access_token":"tok_abcdefghijklmnopqrstuvwxyz"}',
            link_type="paypal",
        )

    def test_stream_event_keeps_chinese_and_ndjson_shape(self) -> None:
        line = app.stream_event("log", {"message": "正在创建 checkout。"})

        self.assertTrue(line.endswith("\n"))
        payload = json.loads(line)
        self.assertEqual(payload["event"], "log")
        self.assertEqual(payload["message"], "正在创建 checkout。")

    def test_chatgpt_approve_with_retry_reuses_cs_until_approved(self) -> None:
        checkout = {
            "billing_country": "US",
            "processor_entity": "openai_llc",
        }
        responses = [
            FakeApproveResponse("blocked"),
            FakeApproveResponse("blocked"),
            FakeApproveResponse("approved"),
        ]
        called_urls: list[str] = []
        progress_events: list[tuple[str, dict | None]] = []

        def fake_post(url: str, **_kwargs):
            called_urls.append(url)
            if url.endswith("/sentinel/ping"):
                return FakeApproveResponse("ok")
            return responses.pop(0)

        chatgpt = SimpleNamespace(post=fake_post)

        with patch.object(app.time, "sleep", return_value=None):
            app.chatgpt_approve_with_retry(
                chatgpt,
                "cs_live_same",
                checkout,
                max_attempts=5,
                progress=lambda step, _message, data=None: progress_events.append((step, data)),
            )

        approve_calls = [url for url in called_urls if url.endswith("/checkout/approve")]
        self.assertEqual(len(approve_calls), 3)
        self.assertEqual(len(set(approve_calls)), 1)
        self.assertTrue(
            any(
                (data or {}).get("approve_result") == "approved" or (data or {}).get("result") == "approved"
                for _step, data in progress_events
            )
        )

    def test_chatgpt_approve_with_retry_raises_after_blocked_limit(self) -> None:
        checkout = {
            "billing_country": "US",
            "processor_entity": "openai_llc",
        }
        called_urls: list[str] = []

        def fake_post(url: str, **_kwargs):
            called_urls.append(url)
            return FakeApproveResponse("blocked")

        chatgpt = SimpleNamespace(post=fake_post)

        with patch.object(app.time, "sleep", return_value=None):
            with self.assertRaises(app.HTTPException) as exc:
                app.chatgpt_approve_with_retry(
                    chatgpt,
                    "cs_live_blocked",
                    checkout,
                    max_attempts=2,
                )

        approve_calls = [url for url in called_urls if url.endswith("/checkout/approve")]
        self.assertEqual(len(approve_calls), 2)
        self.assertIn("chatgpt approve 重试耗尽", str(exc.exception.detail))

    def test_chatgpt_approve_with_retry_stops_when_after_attempt_finds_redirect(self) -> None:
        checkout = {
            "billing_country": "US",
            "processor_entity": "openai_llc",
        }
        called_urls: list[str] = []

        def fake_post(url: str, **_kwargs):
            called_urls.append(url)
            return FakeApproveResponse("blocked")

        chatgpt = SimpleNamespace(post=fake_post)

        with patch.object(app.time, "sleep", return_value=None):
            redirect_url, approve_result = app.chatgpt_approve_with_retry(
                chatgpt,
                "cs_live_same",
                checkout,
                max_attempts=5,
                after_attempt=lambda _attempt, _max_attempts, _result: "https://pm-redirects.stripe.com/test",
            )

        approve_calls = [url for url in called_urls if url.endswith("/checkout/approve")]
        self.assertEqual(len(approve_calls), 1)
        self.assertEqual(redirect_url, "https://pm-redirects.stripe.com/test")
        self.assertEqual(approve_result, "blocked")

    def test_redirect_uses_request_approve_retries(self) -> None:
        captured: dict[str, int] = {}
        req = app.LongLinkRequest(
            accessToken="tok_test",
            link_type="paypal",
            approveRetries=7,
        )
        checkout = {
            "billing_country": "US",
            "processor_entity": "openai_llc",
        }
        confirm_payload = {"submission_attempt": {"state": "requires_approval"}}

        def fake_approve(_chatgpt, _cs_id, _checkout, max_attempts, progress, after_attempt=None, **kwargs):
            captured["max_attempts"] = max_attempts
            captured["pool_size"] = kwargs.get("pool_size")
            return "", "approved"

        with (
            patch.object(app, "chatgpt_approve_with_retry", side_effect=fake_approve),
            patch.object(app, "stripe_payment_page_redirect_url", return_value="https://pm-redirects.stripe.com/test"),
        ):
            url, approve_result = app.redirect_url_after_confirm(
                SimpleNamespace(),
                SimpleNamespace(),
                confirm_payload,
                "cs_live_same",
                "pk_test",
                checkout,
                req,
            )

        self.assertEqual(url, "https://pm-redirects.stripe.com/test")
        self.assertEqual(approve_result, "approved")
        self.assertGreaterEqual(captured["max_attempts"], 7)
        self.assertEqual(captured["pool_size"], 30)

    def test_stripe_context_reuses_init_stripe_js_id(self) -> None:
        req = self.make_request()

        ctx = app.stripe_context(
            "cs_test_reuse",
            {
                "_stripe_js_id": "js_fixed_123",
                "_elements_locale": "en",
                "config_id": "cfg_test_123",
                "init_checksum": "checksum_test_123",
                "currency": "usd",
            },
            req,
        )

        self.assertEqual(ctx["stripe_js_id"], "js_fixed_123")
        self.assertEqual(ctx["locale"], "en")

    def test_stripe_setup_intent_redirect_url_from_payload_retrieves_next_action(self) -> None:
        seen_calls: list[tuple[str, dict]] = []

        def fake_get(url: str, **kwargs):
            seen_calls.append((url, kwargs))
            return FakeHttpResponse(
                status_code=200,
                json_data={
                    "id": "seti_123",
                    "status": "requires_action",
                    "next_action": {
                        "type": "redirect_to_url",
                        "redirect_to_url": {"url": "https://hooks.stripe.com/next_action"},
                    },
                },
                url=url,
            )

        stripe = SimpleNamespace(get=fake_get)
        redirect_url = app.stripe_setup_intent_redirect_url_from_payload(
            stripe,
            {"setup_intent": {"id": "seti_123", "client_secret": "seti_123_secret_456"}},
            "pk_test_123",
        )

        self.assertEqual(redirect_url, "https://hooks.stripe.com/next_action")
        self.assertIn("/v1/setup_intents/seti_123", seen_calls[0][0])
        self.assertEqual(seen_calls[0][1]["params"]["client_secret"], "seti_123_secret_456")

    def test_resolve_external_redirect_extracts_paypal_url_from_html(self) -> None:
        paypal_url = "https://www.paypal.com/agreements/approve?ba_token=BA-TEST123"

        def fake_get(url: str, **_kwargs):
            return FakeHttpResponse(
                status_code=200,
                text=f'<script>window.__NEXT__="{paypal_url.replace("/", "\\/")}"</script>',
                url=url,
            )

        stripe = SimpleNamespace(get=fake_get)

        resolved = app.resolve_external_redirect(
            stripe,
            "https://pm-redirects.stripe.com/pay/test",
            preferred_hosts=("paypal.com",),
        )

        self.assertEqual(resolved, paypal_url)

    def test_create_provider_link_recovers_from_hosted_page_after_redirect_timeout(self) -> None:
        req = self.make_request()
        checkout = {
            "cs_id": "cs_live_timeout",
            "billing_country": "US",
            "processor_entity": "openai_llc",
        }
        init_payload = {
            "_stripe_js_id": "js_fixed_123",
            "_elements_locale": "en",
            "config_id": "cfg_test_123",
            "init_checksum": "checksum_test_123",
            "currency": "usd",
        }
        paypal_url = "https://www.paypal.com/agreements/approve?ba_token=BA-RECOVERED"
        progress_events: list[tuple[str, str, dict | None]] = []

        def fake_resolve(_stripe, current: str, preferred_hosts=(), max_hops: int = 5):
            if "pay.openai.com" in current or "checkout.stripe.com" in current:
                return paypal_url
            return current

        with (
            patch.object(app, "stripe_create_payment_method", return_value="pm_test_123"),
            patch.object(app, "stripe_confirm", return_value={"submission_attempt": {"state": "requires_approval"}}),
            patch.object(
                app,
                "redirect_url_after_confirm",
                side_effect=app.HTTPException(status_code=504, detail="redirect url resolution timeout"),
            ),
            patch.object(app, "resolve_external_redirect", side_effect=fake_resolve),
        ):
            result = app.create_provider_link(
                SimpleNamespace(),
                checkout,
                init_payload,
                "https://checkout.stripe.com/c/pay/cs_live_timeout",
                req,
                stripe_session=SimpleNamespace(),
                progress=lambda step, message, data=None: progress_events.append((step, message, data)),
            )

        self.assertEqual(result["provider_redirect_url"], paypal_url)
        self.assertEqual(result["long_url"], paypal_url)
        self.assertEqual(result["stripe_redirect_url"], "")
        self.assertTrue(any(step == "provider_recover" for step, _message, _data in progress_events))

    def test_pause_controller_blocks_until_resume(self) -> None:
        controller = app.PauseController()
        finished: list[bool] = []
        controller.pause()

        thread = threading.Thread(target=lambda: (controller.wait_if_paused(), finished.append(True)))
        thread.start()
        time.sleep(0.02)
        self.assertEqual(finished, [])

        controller.resume()
        thread.join(timeout=1)
        self.assertEqual(finished, [True])

    def test_task_pause_state_controls_registered_task(self) -> None:
        task_id = "task_test_pause"
        app.get_or_create_task_controller(task_id)
        try:
            paused = app.set_task_pause_state(task_id, True)
            resumed = app.set_task_pause_state(task_id, False)
        finally:
            app.release_task_controller(task_id)

        self.assertTrue(paused["paused"])
        self.assertFalse(resumed["paused"])

    def test_task_terminate_wakes_paused_controller(self) -> None:
        controller = app.PauseController()
        errors: list[str] = []
        controller.pause()

        def wait_for_resume() -> None:
            try:
                controller.wait_if_paused()
            except app.TaskCancelled as exc:
                errors.append(str(exc))

        thread = threading.Thread(target=wait_for_resume)
        thread.start()
        time.sleep(0.02)
        controller.cancel()
        thread.join(timeout=1)

        self.assertEqual(errors, ["任务已终止"])

    def test_terminate_task_marks_registered_controller_cancelled(self) -> None:
        task_id = "task_test_terminate"
        controller = app.get_or_create_task_controller(task_id)
        try:
            result = app.terminate_task(task_id)
            self.assertTrue(result["cancelled"])
            self.assertTrue(controller.is_cancelled())
        finally:
            app.release_task_controller(task_id)

    def test_generate_core_reports_progress_without_real_network(self) -> None:
        req = self.make_request()
        messages: list[str] = []

        def progress(_step: str, message: str, _data=None) -> None:
            messages.append(message)

        with (
            patch.object(app, "build_chatgpt_session", return_value=SimpleNamespace()),
            patch.object(
                app,
                "create_checkout",
                return_value={
                    "cs_id": "cs_test_123",
                    "processor_entity": "openai_llc",
                    "billing_country": "US",
                    "currency": "USD",
                },
            ),
            patch.object(
                app,
                "stripe_init",
                return_value={"stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test_123"},
            ),
            patch.object(
                app,
                "create_provider_link",
                return_value={
                    "payment_method_id": "pm_test_123",
                    "stripe_redirect_url": "https://hooks.stripe.com/test",
                    "provider_redirect_url": "https://www.paypal.com/agreements/approve?ba_token=BA-TEST",
                    "long_url": "https://www.paypal.com/agreements/approve?ba_token=BA-TEST",
                },
            ),
        ):
            result = app.generate_long_link_core(req, progress=progress)

        self.assertEqual(result.link_type, "paypal")
        self.assertEqual(result.long_url, "https://www.paypal.com/agreements/approve?ba_token=BA-TEST")
        self.assertTrue(any("checkout 创建成功" in message for message in messages))
        self.assertTrue(any("生成流程完成" in message for message in messages))

    def test_generate_core_keeps_chatgpt_on_checkout_proxy_for_approve(self) -> None:
        req = app.LongLinkRequest(
            accessToken='{"access_token":"tok_abcdefghijklmnopqrstuvwxyz"}',
            link_type="paypal",
            checkout_proxy="http://checkout.proxy:9000",
            provider_proxy="http://provider.proxy:9100",
        )
        chatgpt_session = SimpleNamespace(proxies={"http": "http://checkout.proxy:9000"})
        seen_provider_proxy: list[str] = []
        progress_events: list[tuple[str, str, dict | None]] = []

        def progress(step: str, message: str, data=None) -> None:
            progress_events.append((step, message, data))

        def fake_provider_link(chatgpt, *_args, provider_proxy="", **_kwargs) -> dict[str, str]:
            self.assertIs(chatgpt, chatgpt_session)
            self.assertEqual(chatgpt.proxies["http"], "http://checkout.proxy:9000")
            seen_provider_proxy.append(provider_proxy)
            return {
                "payment_method_id": "pm_test_123",
                "stripe_redirect_url": "https://hooks.stripe.com/test",
                "provider_redirect_url": "https://www.paypal.com/agreements/approve?ba_token=BA-TEST",
                "long_url": "https://www.paypal.com/agreements/approve?ba_token=BA-TEST",
            }

        with (
            patch.object(app, "build_chatgpt_session", return_value=chatgpt_session),
            patch.object(
                app,
                "create_checkout",
                return_value={
                    "cs_id": "cs_test_123",
                    "processor_entity": "openai_llc",
                    "billing_country": "US",
                    "currency": "USD",
                },
            ),
            patch.object(
                app,
                "stripe_init",
                return_value={"stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test_123"},
            ),
            patch.object(app, "create_provider_link", side_effect=fake_provider_link),
        ):
            result = app.generate_long_link_core(req, progress=progress)

        self.assertTrue(result.ok)
        self.assertEqual(seen_provider_proxy, ["http://provider.proxy:9100"])
        self.assertTrue(
            any(
                step == "chatgpt_session"
                and (data or {}).get("actual_protocol") == "http"
                and (data or {}).get("actual_proxy") == "http://checkout.proxy:9000"
                for step, _message, data in progress_events
            )
        )

    def test_generate_core_uses_checkout_proxy_for_stripe_init_then_switches_same_session_to_provider(self) -> None:
        req = app.LongLinkRequest(
            accessToken='{"access_token":"tok_abcdefghijklmnopqrstuvwxyz"}',
            link_type="paypal",
            checkout_proxy="http://checkout.proxy:9000",
            provider_proxy="http://provider.proxy:9100",
        )
        stripe_session = requests.Session()
        seen: dict[str, object] = {}

        def fake_stripe_init(_cs_id, _req, proxy_override="", stripe_session=None):
            seen["init_proxy"] = proxy_override
            seen["init_session_same"] = stripe_session is stripe_session_ref
            return {"stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test_123"}

        def fake_provider_link(_chatgpt, _checkout, _init_payload, _stripe_hosted_url, _req, provider_proxy="", stripe_session=None, **_kwargs):
            seen["provider_proxy"] = provider_proxy
            seen["provider_session_same"] = stripe_session is stripe_session_ref
            seen["provider_session_http_proxy"] = stripe_session.proxies.get("http")
            return {
                "payment_method_id": "pm_test_123",
                "stripe_redirect_url": "https://hooks.stripe.com/test",
                "provider_redirect_url": "https://www.paypal.com/agreements/approve?ba_token=BA-TEST",
                "long_url": "https://www.paypal.com/agreements/approve?ba_token=BA-TEST",
            }

        stripe_session_ref = stripe_session

        with (
            patch.object(app, "build_chatgpt_session", return_value=SimpleNamespace()),
            patch.object(
                app,
                "create_checkout",
                return_value={
                    "cs_id": "cs_test_123",
                    "processor_entity": "openai_llc",
                    "billing_country": "US",
                    "currency": "USD",
                },
            ),
            patch.object(app, "build_stripe_session", return_value=stripe_session_ref),
            patch.object(app, "stripe_init", side_effect=fake_stripe_init),
            patch.object(app, "create_provider_link", side_effect=fake_provider_link),
        ):
            result = app.generate_long_link_core(req)

        self.assertTrue(result.ok)
        self.assertEqual(seen["init_proxy"], "http://checkout.proxy:9000")
        self.assertTrue(seen["init_session_same"])
        self.assertEqual(seen["provider_proxy"], "http://provider.proxy:9100")
        self.assertTrue(seen["provider_session_same"])
        self.assertEqual(seen["provider_session_http_proxy"], "http://provider.proxy:9100")

    def test_generate_core_retries_when_provider_falls_back(self) -> None:
        req = self.make_request()
        progress_events: list[tuple[str, str, dict | None]] = []
        attempts = {"count": 0}

        def progress(step: str, message: str, data=None) -> None:
            progress_events.append((step, message, data))

        def fake_provider_link(*_args, **_kwargs) -> dict[str, str]:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise app.HTTPException(status_code=502, detail=f"provider 第 {attempts['count']} 轮失败")
            return {
                "payment_method_id": "pm_test_123",
                "stripe_redirect_url": "https://hooks.stripe.com/test",
                "provider_redirect_url": "https://www.paypal.com/agreements/approve?ba_token=BA-FINAL",
                "long_url": "https://www.paypal.com/agreements/approve?ba_token=BA-FINAL",
            }

        with (
            patch.object(app, "build_chatgpt_session", return_value=SimpleNamespace()),
            patch.object(
                app,
                "create_checkout",
                return_value={
                    "cs_id": "cs_test_123",
                    "processor_entity": "openai_llc",
                    "billing_country": "US",
                    "currency": "USD",
                },
            ),
            patch.object(
                app,
                "stripe_init",
                return_value={"stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test_123"},
            ),
            patch.object(app, "create_provider_link", side_effect=fake_provider_link),
        ):
            result = app.generate_long_link_core(req, progress=progress)

        self.assertTrue(result.ok)
        self.assertFalse(result.fallback)
        self.assertEqual(result.attempt_count, 3)
        self.assertEqual(result.max_attempts, 5)
        self.assertEqual(len(result.retry_history), 3)
        self.assertEqual(result.retry_history[0].attempt, 1)
        self.assertFalse(result.retry_history[0].ok)
        self.assertEqual(result.retry_history[-1].attempt, 3)
        self.assertTrue(result.retry_history[-1].ok)
        self.assertTrue(
            any(
                step == "retry" and (data or {}).get("phase") == "attempt_failed" and (data or {}).get("will_retry") is True
                for step, _message, data in progress_events
            )
        )

    def test_generate_core_returns_last_hosted_after_retry_limit(self) -> None:
        req = app.LongLinkRequest(
            accessToken='{"access_token":"tok_abcdefghijklmnopqrstuvwxyz"}',
            link_type="paypal",
            maxRetries=3,
        )

        with (
            patch.object(app, "build_chatgpt_session", return_value=SimpleNamespace()),
            patch.object(
                app,
                "create_checkout",
                return_value={
                    "cs_id": "cs_test_456",
                    "processor_entity": "openai_llc",
                    "billing_country": "US",
                    "currency": "USD",
                },
            ),
            patch.object(
                app,
                "stripe_init",
                return_value={"stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_test_456"},
            ),
            patch.object(app, "create_provider_link", side_effect=app.HTTPException(status_code=502, detail="provider 一直失败")),
        ):
            result = app.generate_long_link_core(req)

        self.assertFalse(result.ok)
        self.assertTrue(result.fallback)
        self.assertEqual(result.attempt_count, 3)
        self.assertEqual(result.max_attempts, 3)
        self.assertEqual(result.long_url, "https://pay.openai.com/c/pay/cs_test_456")
        self.assertEqual(len(result.retry_history), 3)
        self.assertTrue(all(not item.ok for item in result.retry_history))
        self.assertTrue(all(item.fallback for item in result.retry_history))

    def test_normalize_max_retries_bounds(self) -> None:
        self.assertEqual(app.normalize_max_retries(0), 1)
        self.assertEqual(app.normalize_max_retries(99), 20)
        self.assertEqual(app.normalize_max_retries("bad"), 5)

    def test_normalize_approve_retries_bounds(self) -> None:
        self.assertEqual(app.normalize_approve_retries(0), 1)
        self.assertEqual(app.normalize_approve_retries(99), 30)
        self.assertEqual(app.normalize_approve_retries("bad"), 10)

    def test_public_paypal_request_passes_approve_retries(self) -> None:
        req = app.PublicPayPalLinkRequest(
            accessToken='{"access_token":"tok_abcdefghijklmnopqrstuvwxyz"}',
            maxRetries=5,
            approveRetries=12,
        )

        inner = app.build_public_paypal_request(req)

        self.assertEqual(inner.approve_retries, 12)

    def test_public_paypal_request_accepts_session_and_defaults_to_direct_pm_redirect(self) -> None:
        req = app.PublicPayPalLinkRequest(
            session='{"access_token":"tok_abcdefghijklmnopqrstuvwxyz"}',
            maxRetries=5,
        )

        inner = app.build_public_paypal_request(req)

        self.assertEqual(inner.access_token, '{"access_token":"tok_abcdefghijklmnopqrstuvwxyz"}')
        self.assertEqual(app.normalize_access_token(inner.access_token), "tok_abcdefghijklmnopqrstuvwxyz")
        self.assertEqual(inner.link_type, "paypal")
        self.assertTrue(inner.all_no_proxy)
        self.assertFalse(inner.fetch_ba_token)
        self.assertEqual(inner.proxy, "")
        self.assertEqual(inner.checkout_proxy, "")
        self.assertEqual(inner.provider_proxy, "")

    def test_public_paypal_request_uses_proxy_when_explicit_proxy_is_provided(self) -> None:
        req = app.PublicPayPalLinkRequest(
            session='{"access_token":"tok_abcdefghijklmnopqrstuvwxyz"}',
            proxy="http://127.0.0.1:3010",
            maxRetries=5,
        )

        inner = app.build_public_paypal_request(req)

        self.assertFalse(inner.all_no_proxy)
        self.assertEqual(inner.proxy, "http://127.0.0.1:3010")

    def test_get_paypal_link_returns_success_when_pm_redirect_exists(self) -> None:
        req = app.PublicPayPalLinkRequest(
            session='{"access_token":"tok_abcdefghijklmnopqrstuvwxyz"}',
            maxRetries=5,
        )
        pm_redirect = "https://pm-redirects.stripe.com/authorize/test"

        fake_result = app.LongLinkResponse(
            ok=True,
            cs_id="cs_test_ok",
            processor_entity="openai_llc",
            billing_country="US",
            currency="USD",
            payment_locale="en",
            link_type="paypal",
            payment_method_type="paypal",
            payment_method_id="pm_test_ok",
            stripe_redirect_url=pm_redirect,
            provider_redirect_url="https://www.paypal.com/agreements/approve?ba_token=BA-1SU08173WH746842C",
            pm_redirect_url=pm_redirect,
            fallback=False,
            provider_error="",
            stripe_hosted_url="https://checkout.stripe.com/c/pay/cs_test_ok",
            long_url="https://www.paypal.com/agreements/approve?ba_token=BA-1SU08173WH746842C",
            attempt_count=1,
            max_attempts=5,
            retry_history=[app.RetryHistoryItem(attempt=1, ok=True, long_url="https://www.paypal.com/agreements/approve?ba_token=BA-1SU08173WH746842C")],
        )

        with patch.object(app, "generate_long_link_core", return_value=fake_result):
            response = app.get_paypal_link(req)

        self.assertTrue(response.success)
        self.assertEqual(response.code, "SUCCESS")
        self.assertEqual(response.paypal_link, pm_redirect)
        self.assertEqual(response.pm_redirect_url, pm_redirect)
        self.assertEqual(response.attempt_count, 1)
        self.assertEqual(response.max_attempts, 5)
        self.assertEqual(response.retries_used, 0)

    def test_get_paypal_link_returns_failure_when_fallback_hosted_only(self) -> None:
        req = app.PublicPayPalLinkRequest(
            accessToken='{"access_token":"tok_abcdefghijklmnopqrstuvwxyz"}',
            maxRetries=5,
        )

        fake_result = app.LongLinkResponse(
            ok=False,
            cs_id="cs_test_fail",
            processor_entity="openai_llc",
            billing_country="US",
            currency="USD",
            payment_locale="en",
            link_type="paypal",
            payment_method_type="paypal",
            payment_method_id="pm_test_fail",
            stripe_redirect_url="https://pm-redirects.stripe.com/test",
            provider_redirect_url="",
            fallback=True,
            provider_error="provider 提取失败，已回退 hosted。",
            stripe_hosted_url="https://checkout.stripe.com/c/pay/cs_test_fail",
            long_url="https://pay.openai.com/c/pay/cs_test_fail",
            attempt_count=5,
            max_attempts=5,
            retry_history=[
                app.RetryHistoryItem(attempt=1, ok=False, error="provider 第 1 轮失败", fallback=True),
                app.RetryHistoryItem(attempt=5, ok=False, error="provider 提取失败，已回退 hosted。", fallback=True),
            ],
        )

        with patch.object(app, "generate_long_link_core", return_value=fake_result):
            response = app.get_paypal_link(req)

        self.assertFalse(response.success)
        self.assertEqual(response.code, "PAYPAL_LINK_NOT_FOUND")
        self.assertEqual(response.paypal_link, "")
        self.assertEqual(response.hosted_long_url, "https://pay.openai.com/c/pay/cs_test_fail")
        self.assertEqual(response.attempt_count, 5)
        self.assertEqual(response.max_attempts, 5)
        self.assertEqual(response.last_error, "provider 提取失败，已回退 hosted。")

    def test_get_paypal_link_returns_invalid_input_for_missing_token(self) -> None:
        req = app.PublicPayPalLinkRequest(accessToken="", sessionJson="", maxRetries=5)

        response = app.get_paypal_link(req)

        self.assertFalse(response.success)
        self.assertEqual(response.code, "INVALID_INPUT")
        self.assertEqual(response.attempt_count, 0)
        self.assertEqual(response.max_attempts, 5)

    def test_get_paypal_link_collects_retry_error_when_upstream_exception_raised(self) -> None:
        req = app.PublicPayPalLinkRequest(
            accessToken='{"access_token":"tok_abcdefghijklmnopqrstuvwxyz"}',
            maxRetries=3,
        )

        captured_progress = {}

        def fake_generate(_req, progress):
            progress(
                "retry",
                "第 3/3 轮失败，准备自动重试。",
                {
                    "attempt": 3,
                    "max_attempts": 3,
                    "error": "provider 一直失败",
                    "phase": "attempt_failed",
                    "will_retry": False,
                },
            )
            raise app.HTTPException(status_code=502, detail="provider 一直失败")

        with patch.object(app, "generate_long_link_core", side_effect=fake_generate):
            response = app.get_paypal_link(req)

        self.assertFalse(response.success)
        self.assertEqual(response.code, "UPSTREAM_ERROR")
        self.assertEqual(response.attempt_count, 3)
        self.assertEqual(response.max_attempts, 3)
        self.assertEqual(response.last_error, "provider 一直失败")
        self.assertEqual(response.retry_history[-1].error, "provider 一直失败")


class ProxyCheckTests(unittest.TestCase):
    def test_effective_country_for_paypal_is_us(self) -> None:
        req = app.LongLinkRequest(accessToken="tok_test", link_type="paypal")

        self.assertEqual(app.effective_country(req), "US")

    def test_checkout_stage_proxy_prefers_checkout_proxy(self) -> None:
        req = app.LongLinkRequest(
            accessToken="tok_test",
            proxy="http://legacy.proxy:8000",
            checkout_proxy="http://checkout.proxy:9000",
        )

        self.assertEqual(app.checkout_stage_proxy(req), "http://checkout.proxy:9000")

    def test_checkout_stage_proxy_uses_default_jp_proxy_when_not_provided(self) -> None:
        req = app.LongLinkRequest(accessToken="tok_test")

        with patch.object(
            app,
            "DEFAULT_PROXY",
            "socks5://bj2m1188418-region-jp:nanno2@us.cliproxy.io:3010",
        ):
            self.assertEqual(
                app.checkout_stage_proxy(req),
                "socks5://bj2m1188418-region-jp:nanno2@us.cliproxy.io:3010",
            )

    def test_provider_stage_proxy_uses_us_proxy_instead_of_checkout_proxy(self) -> None:
        req = app.LongLinkRequest(
            accessToken="tok_test",
            link_type="paypal",
            checkout_proxy="http://checkout.proxy:9000",
        )

        with (
            patch.object(
                app,
                "DEFAULT_PROXY",
                "socks5://bj2m1188418-region-jp:nanno2@us.cliproxy.io:3010",
            ),
            patch.object(app, "PROVIDER_STAGE_PROXY", ""),
        ):
            self.assertEqual(
                app.provider_stage_proxy(req),
                "socks5://bj2m1188418-region-US:nanno2@us.cliproxy.io:3010",
            )

    def test_provider_stage_proxy_prefers_explicit_provider_proxy(self) -> None:
        req = app.LongLinkRequest(
            accessToken="tok_test",
            link_type="paypal",
            checkout_proxy="http://checkout.proxy:9000",
            provider_proxy="http://provider.proxy:9100",
        )

        self.assertEqual(app.provider_stage_proxy(req), "http://provider.proxy:9100")

    def test_paypal_billing_uses_us_address(self) -> None:
        billing = app.billing_for_link_type("paypal")

        self.assertEqual(billing["country"], "US")
        self.assertIn(billing["state"], {"CA", "TX", "NY", "GA"})

    def test_extract_stripe_terminal_error_reads_payment_method_from_last_setup_error(self) -> None:
        detail = app.extract_stripe_terminal_error(
            {
                "setup_intent": {
                    "status": "requires_payment_method",
                    "payment_method": None,
                    "last_setup_error": {
                        "code": "setup_attempt_failed",
                        "decline_code": "generic_decline",
                        "message": "The latest attempt to set up the payment method has failed.",
                        "payment_method": {
                            "type": "paypal",
                            "billing_details": {"address": {"country": "US"}},
                        },
                    },
                }
            }
        )

        self.assertIn("payment_method.type=paypal", detail)
        self.assertIn("billing_details.address.country=US", detail)

    def test_provider_stage_proxy_uses_default_us_proxy_for_paypal_when_not_provided(self) -> None:
        req = app.LongLinkRequest(accessToken="tok_test", link_type="paypal")

        with (
            patch.object(
                app,
                "DEFAULT_PROXY",
                "socks5://bj2m1188418-region-jp:nanno2@us.cliproxy.io:3010",
            ),
            patch.object(app, "PROVIDER_STAGE_PROXY", ""),
        ):
            self.assertEqual(
                app.provider_stage_proxy(req),
                "socks5://bj2m1188418-region-US:nanno2@us.cliproxy.io:3010",
            )

    def test_normalize_proxy_url_host_port_user_pass(self) -> None:
        proxy = app.normalize_proxy_url("proxy.example.com:3010:user:pass")

        self.assertEqual(proxy, "http://user:pass@proxy.example.com:3010")

    def test_proxy_candidates_try_http_before_socks5(self) -> None:
        candidates = app.proxy_candidates("socks5://user:pass@proxy.example.com:3010")

        self.assertEqual(candidates[0], "http://user:pass@proxy.example.com:3010")
        self.assertEqual(candidates[1], "socks5://user:pass@proxy.example.com:3010")

    def test_proxy_runtime_details_reports_http_for_curl_session(self) -> None:
        class FakeCurlSession:
            def __init__(self) -> None:
                self.proxies = {}

        session = FakeCurlSession()
        original = app.CurlCffiSession
        try:
            app.CurlCffiSession = FakeCurlSession
            app.set_proxy_url(session, "socks5://user:pass@proxy.example.com:3010")
            details = app.proxy_runtime_details(session, "socks5://user:pass@proxy.example.com:3010")
        finally:
            app.CurlCffiSession = original

        self.assertEqual(details["actual_protocol"], "http")
        self.assertEqual(details["actual_proxy"], "http://proxy.example.com:3010")
        self.assertEqual(details["session_impl"], "curl_cffi")

    def test_set_proxy_url_prefers_http_candidate_for_curl_session(self) -> None:
        class FakeCurlSession:
            def __init__(self) -> None:
                self.proxies = {}

        session = FakeCurlSession()
        original = app.CurlCffiSession
        try:
            app.CurlCffiSession = FakeCurlSession
            app.set_proxy_url(session, "socks5://user:pass@proxy.example.com:3010")
        finally:
            app.CurlCffiSession = original

        self.assertEqual(
            session.proxies,
            {
                "http": "http://user:pass@proxy.example.com:3010",
                "https": "http://user:pass@proxy.example.com:3010",
            },
        )

    def test_set_proxy_url_keeps_original_proxy_for_requests_session(self) -> None:
        session = requests.Session()

        app.set_proxy_url(session, "socks5://user:pass@proxy.example.com:3010")

        self.assertEqual(
            session.proxies,
            {
                "http": "socks5://user:pass@proxy.example.com:3010",
                "https": "socks5://user:pass@proxy.example.com:3010",
            },
        )

    def test_check_proxy_info_normalizes_probe_payload(self) -> None:
        with patch.object(app.requests, "get", return_value=FakeProxyResponse()) as mocked_get:
            info = app.check_proxy_info("socks5://user:pass@proxy.example.com:3010")

        self.assertEqual(info["ip"], "125.103.37.73")
        self.assertEqual(info["country_display"], "Japan（日本）")
        self.assertEqual(info["city"], "Fuke")
        self.assertEqual(info["protocol"], "http")
        self.assertIn("proxy.example.com:3010", mocked_get.call_args.kwargs["proxies"]["http"])

    def test_check_proxy_route_exists(self) -> None:
        paths = {route.path for route in app.app.routes}

        self.assertIn("/api/check-proxy", paths)
        self.assertIn("/api/plus/payment-link/check-proxy", paths)

    def test_build_proxy_check_response_uses_current_run_stages(self) -> None:
        req = app.ProxyCheckRequest(proxy_input="proxy.example.com:3010:user:pass", link_type="paypal")

        with patch.object(
            app,
            "check_proxy_info",
            return_value={
                "ip": "125.103.37.73",
                "country_display": "Japan（日本）",
                "country_code": "JP",
                "city": "Fuke",
                "isp": "broadgate-un",
                "org": "broadgate-un",
                "protocol": "http",
                "source": "ip-api.com",
            },
        ):
            response = app.build_proxy_check_response(req)

        self.assertTrue(response.ok)
        self.assertEqual(response.checks[0].stage, "checkout")
        self.assertEqual(response.checks[0].country, "Japan（日本）")
        self.assertEqual(response.checks[0].selection_kind, "custom")
        self.assertEqual(response.checks[0].selection_source, "请求代理输入")
        self.assertEqual(response.checks[1].stage, "provider")
        self.assertEqual(response.checks[1].selection_kind, "builtin")
        self.assertIn("provider", response.checks[1].selection_source)

    def test_build_proxy_check_response_for_provider_stage_only(self) -> None:
        req = app.ProxyCheckRequest(
            link_type="paypal",
            stage="provider",
            checkout_proxy="http://checkout.proxy:9000",
            provider_proxy="http://provider.proxy:9100",
        )

        with patch.object(
            app,
            "check_proxy_info",
            return_value={
                "ip": "125.103.37.73",
                "country_display": "Japan（日本）",
                "country_code": "JP",
                "city": "Fuke",
                "isp": "broadgate-un",
                "org": "broadgate-un",
                "protocol": "http",
                "source": "ip-api.com",
            },
        ):
            response = app.build_proxy_check_response(req)

        self.assertTrue(response.ok)
        self.assertEqual(len(response.checks), 1)
        self.assertEqual(response.checks[0].stage, "provider")
        self.assertEqual(response.checks[0].selection_kind, "custom")
        self.assertEqual(response.checks[0].selection_source, "前端自定义 provider 代理")


if __name__ == "__main__":
    unittest.main()
