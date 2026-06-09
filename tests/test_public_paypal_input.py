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


if __name__ == "__main__":
    unittest.main()
