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
            redirect_url, approve_result, pm_redirect_url = app.chatgpt_approve_with_retry(
                chatgpt,
                "cs_live_same",
                checkout,
                max_attempts=5,
                after_attempt=lambda _attempt, _max_attempts, _result: "https://pm-redirects.stripe.com/test",
            )

        approve_calls = [url for url in called_urls if url.endswith("/checkout/approve")]
        self.assertEqual(len(approve_calls), 1)
        self.assertEqual(redirect_url, "https://pm-redirects.stripe.com/test")
        self.assertEqual(pm_redirect_url, "https://pm-redirects.stripe.com/test")
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

        def fake_escalating(_chatgpt, _cs_id, _checkout, **kwargs):
            captured["called"] = 1
            return "", "approved", ""

        with (
            patch.object(app, "chatgpt_approve_escalating", side_effect=fake_escalating),
            patch.object(app, "stripe_payment_page_redirect_url", return_value="https://pm-redirects.stripe.com/test"),
        ):
            url, approve_result, pm_redirect_url = app.redirect_url_after_confirm(
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
        self.assertEqual(captured.get("called"), 1)

    def test_chatgpt_approve_escalation_serial_approved_skips_reapprove_pool(self) -> None:
        checkout = {
            "billing_country": "DE",
            "processor_entity": "openai_ie",
        }
        pool_calls: list[int] = []

        def fake_once(_chatgpt, _cs_id, _checkout):
            return "approved", ""

        def fake_pool(_chatgpt, _cs_id, _checkout, *, pool_size, **_kwargs):
            pool_calls.append(pool_size)
            return "", "approved", ""

        with (
            patch.object(app, "chatgpt_approve_once", side_effect=fake_once),
            patch.object(app, "chatgpt_approve_concurrent_pool", side_effect=fake_pool),
            patch.object(app, "probe_redirect_after_approve", return_value="https://pm-redirects.stripe.com/test"),
        ):
            redirect_url, approve_result, pm_redirect_url = app.chatgpt_approve_escalating(
                SimpleNamespace(post=lambda *_args, **_kwargs: FakeApproveResponse("approved")),
                "cs_live_escalate",
                checkout,
                stripe=SimpleNamespace(),
                req=self.make_request(),
            )

        self.assertEqual(redirect_url, "https://pm-redirects.stripe.com/test")
        self.assertEqual(approve_result, "approved")
        self.assertEqual(pool_calls, [])

    def test_effective_approve_result_keeps_approved(self) -> None:
        self.assertEqual(app.effective_approve_result("approved", "exception"), "approved")
        self.assertEqual(app.effective_approve_result("blocked", "approved"), "approved")

    def test_chatgpt_approve_once_with_parallel_probe_runs_both(self) -> None:
        calls: list[str] = []

        def fake_approve(_chatgpt, _cs_id, _checkout):
            calls.append("approve")
            return "approved", ""

        def fake_probe(*_args, **_kwargs):
            calls.append("probe")
            return "https://pm-redirects.stripe.com/test"

        with (
            patch.object(app, "chatgpt_approve_once", side_effect=fake_approve),
            patch.object(app, "probe_redirect_after_approve", side_effect=fake_probe),
        ):
            result, error_text, redirect_url = app.chatgpt_approve_once_with_parallel_probe(
                SimpleNamespace(),
                "cs_parallel",
                {"billing_country": "DE", "processor_entity": "openai_ie"},
                stripe=SimpleNamespace(),
                stripe_pk="pk_test",
                req=self.make_request(),
            )

        self.assertEqual(result, "approved")
        self.assertEqual(error_text, "")
        self.assertEqual(redirect_url, "https://pm-redirects.stripe.com/test")
        self.assertIn("approve", calls)
        self.assertIn("probe", calls)

    def test_approve_escalation_max_attempts_is_one_per_tier(self) -> None:
        self.assertEqual(app.approve_escalation_max_attempts(2), 1)
        self.assertEqual(app.approve_escalation_max_attempts(30), 1)
        self.assertEqual(app.approve_escalation_wave_attempts(2), 2)
        self.assertEqual(app.approve_escalation_wave_attempts(8), 8)

    def test_approve_escalation_tiers_server_profile_caps_at_two(self) -> None:
        with patch.object(app, "UI_PROFILE", "public"):
            self.assertEqual(app.approve_escalation_tiers(), (1, 2))
            self.assertEqual(app.approve_escalation_tier_label(), "1→2")

    def test_approve_escalation_tiers_local_profile_keeps_thirty(self) -> None:
        with patch.object(app, "UI_PROFILE", "local"):
            self.assertEqual(app.approve_escalation_tiers(), (1, 2, 4, 8, 16, 30))
            self.assertEqual(app.approve_escalation_tier_label(), "1→2→4→8→16→30")

    def test_approve_escalation_exhausted_detail_mentions_server_limit(self) -> None:
        with patch.object(app, "UI_PROFILE", "public"):
            detail = app.approve_escalation_exhausted_detail("blocked", "blocked", total_attempts=4)
        self.assertIn("4 次尝试", detail)
        self.assertIn("最高 2 路", detail)

    def test_normalize_approve_attempt_count_defaults_to_six(self) -> None:
        with patch.object(app, "UI_PROFILE", "local"):
            self.assertEqual(app.normalize_approve_attempt_count(None), 6)
            self.assertEqual(app.normalize_approve_attempt_count(8), 8)

    def test_normalize_approve_attempt_count_server_defaults_and_caps(self) -> None:
        with patch.object(app, "UI_PROFILE", "public"):
            self.assertEqual(app.normalize_approve_attempt_count(None), 4)
            self.assertEqual(app.normalize_approve_attempt_count(8), 4)

    def test_approve_pool_size_for_round_extended_local_uses_thirty(self) -> None:
        with patch.object(app, "UI_PROFILE", "local"):
            self.assertEqual(app.approve_pool_size_for_round(7), 30)
            self.assertEqual(app.approve_pool_size_for_round(8), 30)

    def test_approve_pool_size_for_round_extended_server_caps_at_two(self) -> None:
        with patch.object(app, "UI_PROFILE", "public"):
            self.assertEqual(app.approve_pool_size_for_round(2), 2)
            self.assertEqual(app.approve_pool_size_for_round(4), 2)
            self.assertEqual(app.approve_pool_size_for_round(7), 2)

    def test_chatgpt_approve_escalating_final_round_failure_raises_immediately(self) -> None:
        checkout = {
            "billing_country": "US",
            "processor_entity": "openai_llc",
        }
        req = self.make_request()
        req.approve_attempt_count = 1

        with patch.object(
            app,
            "chatgpt_approve_once_with_parallel_probe",
            return_value=("blocked", "still blocked", ""),
        ):
            with self.assertRaises(app.HTTPException) as exc:
                app.chatgpt_approve_escalating(
                    SimpleNamespace(post=lambda *_args, **_kwargs: FakeApproveResponse("approved")),
                    "cs_live_final",
                    checkout,
                    stripe=SimpleNamespace(),
                    req=req,
                )
        self.assertIn("最后一轮尝试失败", str(exc.exception.detail))

    def test_chatgpt_approve_concurrent_pool_final_round_skips_recovery(self) -> None:
        checkout = {
            "billing_country": "US",
            "processor_entity": "openai_llc",
        }
        req = self.make_request()

        def fake_approve_once(_chatgpt, _cs_id, _checkout, req=None):
            return "blocked", ""

        with (
            patch.object(app.time, "sleep", return_value=None),
            patch.object(app, "chatgpt_approve_once", side_effect=fake_approve_once),
            patch.object(app, "post_approve_redirect_recovery") as recovery_mock,
        ):
            with self.assertRaises(app.HTTPException) as exc:
                app.chatgpt_approve_concurrent_pool(
                    SimpleNamespace(post=lambda *_args, **_kwargs: FakeApproveResponse("ok")),
                    "cs_live_pool_final",
                    checkout,
                    pool_size=2,
                    max_attempts=2,
                    req=req,
                    is_final_round=True,
                )
        recovery_mock.assert_not_called()
        self.assertIn("最后一轮尝试失败", str(exc.exception.detail))

    def test_terminate_task_signals_registered_stop_events(self) -> None:
        task_id = "task_test_stop_signal"
        stop_event = threading.Event()
        app.register_task_stop_event(task_id, stop_event)
        try:
            app.get_or_create_task_controller(task_id)
            app.terminate_task(task_id)
            self.assertTrue(stop_event.is_set())
        finally:
            app.unregister_task_stop_event(task_id, stop_event)
            app.release_task_controller(task_id)

    def test_chatgpt_approve_escalation_serial_blocked_then_upgrades(self) -> None:
        checkout = {
            "billing_country": "US",
            "processor_entity": "openai_llc",
        }
        progress_events: list[str] = []
        pool_sizes: list[int] = []
        pool_max_attempts: list[int] = []

        def fake_once(_chatgpt, _cs_id, _checkout):
            return "blocked", ""

        def fake_pool(_chatgpt, _cs_id, _checkout, *, pool_size, max_attempts, **_kwargs):
            pool_sizes.append(pool_size)
            pool_max_attempts.append(max_attempts)
            return "https://pm-redirects.stripe.com/test", "approved", "https://pm-redirects.stripe.com/test"

        with (
            patch.object(app, "chatgpt_approve_once", side_effect=fake_once),
            patch.object(app, "chatgpt_approve_concurrent_pool", side_effect=fake_pool),
        ):
            redirect_url, approve_result, pm_redirect_url = app.chatgpt_approve_escalating(
                SimpleNamespace(post=lambda *_args, **_kwargs: FakeApproveResponse("approved")),
                "cs_live_escalate",
                checkout,
                stripe=SimpleNamespace(),
                progress=lambda _step, message, _data=None: progress_events.append(message),
            )

        self.assertEqual(redirect_url, "https://pm-redirects.stripe.com/test")
        self.assertEqual(approve_result, "approved")
        self.assertEqual(pool_sizes[0], 2)
        self.assertEqual(pool_max_attempts[0], 2)
        self.assertTrue(any("升级到 2 路并发" in message for message in progress_events))

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

    def test_extract_redirect_to_url_reads_payment_page_top_level_url(self) -> None:
        paypal_url = "https://www.paypal.com/agreements/approve?ba_token=BA-TOP-LEVEL"
        redirect_url = app.extract_redirect_to_url(
            {
                "url": paypal_url,
                "status": "open",
                "payment_status": "unpaid",
            }
        )
        self.assertEqual(redirect_url, paypal_url)

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

    def test_is_paypal_success_url_accepts_pm_redirect_when_fetch_ba_disabled(self) -> None:
        req = self.make_request()
        req.fetch_ba_token = False
        pm_url = "https://pm-redirects.stripe.com/authorize/acct_test/sa_nonce_test"
        self.assertTrue(app.is_paypal_success_url(pm_url, req))
        self.assertFalse(app.is_paypal_success_url("https://pay.openai.com/c/pay/cs_test", req))

    def test_direct_mode_disables_stage_proxies(self) -> None:
        req = self.make_request()
        req.all_no_proxy = True
        self.assertEqual(app.checkout_stage_proxy(req), "")
        self.assertEqual(app.provider_stage_proxy(req), "")
        self.assertEqual(app.approve_stage_proxy(req), "")
        applied = app.apply_payment_strategy(req)
        self.assertEqual(applied.checkout_proxy, "")
        self.assertEqual(applied.provider_proxy, "")
        self.assertEqual(applied.approve_proxy, "")

    def test_pm_redirect_stop_url_returns_pm_when_fetch_ba_disabled(self) -> None:
        req = self.make_request()
        req.fetch_ba_token = False
        pm_url = "https://pm-redirects.stripe.com/authorize/acct_test/sa_nonce_test"
        self.assertEqual(app.pm_redirect_stop_url(req, pm_url), pm_url)
        req.fetch_ba_token = True
        self.assertEqual(app.pm_redirect_stop_url(req, pm_url), "")

    def test_is_paypal_success_url_requires_ba_when_fetch_ba_enabled(self) -> None:
        req = self.make_request()
        req.fetch_ba_token = True
        pm_url = "https://pm-redirects.stripe.com/authorize/acct_test/sa_nonce_test"
        ba_url = "https://www.paypal.com/agreements/approve?ba_token=BA-TEST"
        self.assertFalse(app.is_paypal_success_url(pm_url, req))
        self.assertTrue(app.is_paypal_success_url(ba_url, req))

    def test_stripe_payment_page_redirect_url_single_probe_when_fetch_ba_disabled(self) -> None:
        req = self.make_request()
        req.fetch_ba_token = False
        pm_url = "https://pm-redirects.stripe.com/authorize/acct_test/sa_nonce_test"
        call_count = {"n": 0}

        def fake_get(url: str, **_kwargs):
            call_count["n"] += 1
            return FakeHttpResponse(
                status_code=200,
                json_data={
                    "url": pm_url,
                    "status": "open",
                },
                url=url,
            )

        stripe = SimpleNamespace(get=fake_get)
        resolved = app.stripe_payment_page_redirect_url(
            stripe,
            "cs_live_pm",
            "pk_test",
            req,
            timeout_seconds=30,
        )
        self.assertEqual(resolved, pm_url)
        self.assertEqual(call_count["n"], 1)

    def test_poll_payment_page_provider_url_fast_skips_loop_when_fetch_ba_disabled(self) -> None:
        req = self.make_request()
        req.fetch_ba_token = False
        pm_url = "https://pm-redirects.stripe.com/authorize/acct_test/sa_nonce_test"
        sleep_calls: list[float] = []

        def fake_get(url: str, **_kwargs):
            return FakeHttpResponse(
                status_code=200,
                json_data={"url": pm_url, "status": "open"},
                url=url,
            )

        stripe = SimpleNamespace(get=fake_get)
        with patch.object(app.time, "sleep", side_effect=lambda seconds: sleep_calls.append(seconds)):
            resolved = app.poll_payment_page_provider_url_fast(
                stripe,
                "cs_live_pm",
                "pk_test",
                req,
                timeout_seconds=10,
            )
        self.assertEqual(resolved, pm_url)
        self.assertEqual(sleep_calls, [])

    def test_resolve_pm_redirect_follow_uses_browser_like_redirects(self) -> None:
        paypal_url = "https://www.paypal.com/agreements/approve?ba_token=BA-FOLLOW"
        pm_url = "https://pm-redirects.stripe.com/authorize/acct_test/sa_nonce_test?useWebAuthSession=true"

        def fake_get(url: str, allow_redirects: bool = False, **_kwargs):
            if allow_redirects and "pm-redirects.stripe.com" in url:
                return FakeHttpResponse(status_code=200, text="", url=paypal_url)
            return FakeHttpResponse(status_code=302, headers={"Location": paypal_url}, url=url)

        stripe = SimpleNamespace(get=fake_get)

        resolved = app.resolve_pm_redirect_follow(
            stripe,
            pm_url,
            preferred_hosts=("paypal.com",),
        )

        self.assertEqual(resolved, paypal_url)

    def test_create_provider_link_stops_at_pm_without_resolve_when_fetch_ba_disabled(self) -> None:
        req = self.make_request()
        req.fetch_ba_token = False
        pm_url = "https://pm-redirects.stripe.com/authorize/acct_test/sa_nonce_test?useWebAuthSession=true"
        checkout = {
            "cs_id": "cs_live_pm",
            "billing_country": "DE",
            "processor_entity": "openai_ie",
            "currency": "eur",
        }
        init_payload = {
            "_stripe_js_id": "js_fixed_123",
            "_elements_locale": "de",
            "config_id": "cfg_test_123",
            "init_checksum": "checksum_test_123",
            "currency": "eur",
        }
        progress_events: list[tuple[str, str, dict | None]] = []

        with (
            patch.object(app, "stripe_create_payment_method", return_value="pm_test_123"),
            patch.object(app, "stripe_confirm", return_value={"submission_attempt": {"state": "requires_approval"}}),
            patch.object(
                app,
                "redirect_url_after_confirm",
                return_value=(pm_url, "blocked", pm_url),
            ),
            patch.object(app, "resolve_external_redirect_with_proxy_pool") as resolve_mock,
            patch.object(app, "stripe_payment_page_redirect_url") as repoll_mock,
        ):
            result = app.create_provider_link(
                SimpleNamespace(),
                checkout,
                init_payload,
                "https://checkout.stripe.com/c/pay/cs_live_pm",
                req,
                stripe_session=SimpleNamespace(),
                progress=lambda step, message, data=None: progress_events.append((step, message, data)),
            )

        self.assertEqual(result["long_url"], pm_url)
        self.assertEqual(result["pm_redirect_url"], pm_url)
        resolve_mock.assert_not_called()
        repoll_mock.assert_not_called()
        self.assertTrue(any(data and data.get("stop_polling") for _step, _message, data in progress_events))

    def test_post_approve_redirect_recovery_skips_when_fetch_ba_disabled(self) -> None:
        req = self.make_request()
        req.fetch_ba_token = False
        with patch.object(app, "probe_stripe_redirect_sources") as probe_mock:
            recovered = app.post_approve_redirect_recovery(
                SimpleNamespace(),
                "cs_live_pm",
                "pk_test",
                req,
            )
        self.assertEqual(recovered, "")
        probe_mock.assert_not_called()

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

    def test_raise_if_task_cancelled_uses_registered_controller(self) -> None:
        task_id = "task_test_raise_cancel"
        controller = app.get_or_create_task_controller(task_id)
        req = self.make_request()
        req.task_id = task_id
        try:
            controller.cancel()
            with self.assertRaises(app.TaskCancelled):
                app.raise_if_task_cancelled(req)
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

    def test_generate_core_uses_provider_proxy_for_stripe_init_then_reuses_same_session(self) -> None:
        req = app.LongLinkRequest(
            accessToken='{"access_token":"tok_abcdefghijklmnopqrstuvwxyz"}',
            link_type="paypal",
            checkout_proxy="http://checkout.proxy:9000",
            provider_proxy="http://provider.proxy:9100",
        )
        stripe_session = requests.Session()
        seen: dict[str, object] = {}

        def fake_stripe_init(_cs_id, _req, proxy_override="", stripe_session=None, checkout=None):
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
        self.assertEqual(seen["init_proxy"], "http://provider.proxy:9100")
        self.assertTrue(seen["init_session_same"])
        self.assertEqual(seen["provider_proxy"], "http://provider.proxy:9100")
        self.assertTrue(seen["provider_session_same"])
        self.assertEqual(seen["provider_session_http_proxy"], "http://provider.proxy:9100")

    def test_generate_core_paypal_single_attempt_fails_without_retry(self) -> None:
        req = self.make_request()
        progress_events: list[tuple[str, str, dict | None]] = []
        attempts = {"count": 0}

        def progress(step: str, message: str, data=None) -> None:
            progress_events.append((step, message, data))

        def fake_provider_link(*_args, **_kwargs) -> dict[str, str]:
            attempts["count"] += 1
            raise app.HTTPException(status_code=502, detail=f"provider 第 {attempts['count']} 轮失败")

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

        self.assertFalse(result.ok)
        self.assertTrue(result.fallback)
        self.assertEqual(result.attempt_count, 1)
        self.assertEqual(result.max_attempts, 1)
        self.assertEqual(attempts["count"], 1)
        self.assertEqual(len(result.retry_history), 1)
        self.assertFalse(result.retry_history[0].ok)
        self.assertTrue(result.retry_history[0].fallback)
        self.assertFalse(
            any(
                step == "retry" and (data or {}).get("phase") == "attempt_failed" and (data or {}).get("will_retry") is True
                for step, _message, data in progress_events
            )
        )

    def test_generate_core_paypal_returns_hosted_on_single_failure(self) -> None:
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
        self.assertEqual(result.attempt_count, 1)
        self.assertEqual(result.max_attempts, 1)
        self.assertEqual(result.long_url, "https://pay.openai.com/c/pay/cs_test_456")
        self.assertEqual(len(result.retry_history), 1)
        self.assertTrue(all(not item.ok for item in result.retry_history))
        self.assertTrue(all(item.fallback for item in result.retry_history))

    def test_generate_core_raises_after_link_generation_timeout(self) -> None:
        req = self.make_request()
        start = 1000.0
        expired = start + app.LINK_GENERATION_TIMEOUT_SECONDS + 1

        with patch.object(app.time, "time", side_effect=[start, expired]):
            with self.assertRaises(app.HTTPException) as ctx:
                app.generate_long_link_core(req)

        self.assertEqual(ctx.exception.status_code, 504)
        self.assertIn("60s", str(ctx.exception.detail))

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
        from billing_pools import US_BILLING_STREETS

        billing = app.billing_for_link_type("paypal")
        valid_states = {street[2] for street in US_BILLING_STREETS}

        self.assertEqual(billing["country"], "US")
        self.assertIn(billing["state"], valid_states)

    def test_paypal_billing_de_uses_ascii_safe_address(self) -> None:
        from billing_pools import DE_BILLING_NAMES, DE_BILLING_STREETS

        billing = app.billing_for_link_type("paypal", country="DE")
        valid_states = {street[2] for street in DE_BILLING_STREETS}
        valid_names = {f"{first} {last}" for first, last in DE_BILLING_NAMES}

        self.assertEqual(billing["country"], "DE")
        self.assertIn(billing["state"], valid_states)
        self.assertIn(billing["name"], valid_names)
        self.assertTrue(billing["line1"].isascii())
        self.assertTrue(billing["name"].isascii())

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
