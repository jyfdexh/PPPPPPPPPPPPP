import unittest

import app


class PublicPayPalInputTests(unittest.TestCase):
    def test_session_accepts_full_session_object(self) -> None:
        req = app.PublicPayPalLinkRequest(
            session={
                "user": {"email": "demo@example.com"},
                "accessToken": "tok_from_full_session",
            },
        )

        self.assertEqual(app.resolve_public_paypal_input(req), "tok_from_full_session")

    def test_session_accepts_access_token_string(self) -> None:
        req = app.PublicPayPalLinkRequest(session="tok_direct_session_field")

        self.assertEqual(app.resolve_public_paypal_input(req), "tok_direct_session_field")

    def test_session_json_string_still_extracts_nested_token(self) -> None:
        req = app.PublicPayPalLinkRequest(
            sessionJson='{"nested":{"access_token":"tok_from_session_json"}}',
        )

        self.assertEqual(app.resolve_public_paypal_input(req), "tok_from_session_json")

    def test_access_token_only_uses_server_defaults(self) -> None:
        req = app.PublicPayPalLinkRequest(accessToken="tok_server_default")

        inner = app.build_public_paypal_request(req)

        self.assertEqual(inner.access_token, "tok_server_default")
        self.assertEqual(inner.billing_country, "DE")
        self.assertEqual(inner.payment_locale, "de")
        self.assertEqual(inner.payment_strategy, "jp_de")
        self.assertTrue(inner.all_no_proxy)
        self.assertFalse(inner.fetch_ba_token)
        self.assertEqual(inner.checkout_proxy, "")
        self.assertEqual(inner.provider_proxy, "")

    def test_public_request_defaults_match_page_de_profile(self) -> None:
        req = app.PublicPayPalLinkRequest(session="tok_page_defaults")

        inner = app.build_public_paypal_request(req)

        self.assertEqual(inner.access_token, "tok_page_defaults")
        self.assertEqual(inner.billing_country, "DE")
        self.assertEqual(inner.payment_locale, "de")
        self.assertEqual(inner.payment_strategy, "jp_de")
        self.assertTrue(inner.all_no_proxy)
        self.assertFalse(inner.fetch_ba_token)
        self.assertEqual(inner.approve_attempt_count, 6)

    def test_public_request_allows_us_profile_override(self) -> None:
        req = app.PublicPayPalLinkRequest(
            session="tok_page_defaults",
            billingCountry="US",
            paymentLocale="en",
            paymentStrategy="jp_us",
        )

        inner = app.build_public_paypal_request(req)

        self.assertEqual(inner.billing_country, "US")
        self.assertEqual(inner.payment_locale, "en")
        self.assertEqual(inner.payment_strategy, "jp_us")

    def test_public_request_allows_au_profile_override(self) -> None:
        req = app.PublicPayPalLinkRequest(
            session="tok_page_defaults",
            billingCountry="AU",
            paymentLocale="en",
            paymentStrategy="jp_au",
        )

        inner = app.build_public_paypal_request(req)

        self.assertEqual(inner.billing_country, "AU")
        self.assertEqual(inner.payment_locale, "en")
        self.assertEqual(inner.payment_strategy, "jp_au")


if __name__ == "__main__":
    unittest.main()
