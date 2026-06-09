import unittest

import app


class UiConfigTests(unittest.TestCase):
    def test_public_ui_config_hides_proxy_defaults(self) -> None:
        config = app.build_ui_config("public")

        self.assertEqual(config["profile"], "public")
        self.assertFalse(config["expose_proxy_controls"])
        self.assertEqual(config["proxy_presets"], [])
        self.assertEqual(config["proxy_defaults"]["quick_proxy"], "")
        self.assertEqual(config["proxy_defaults"]["checkout_proxy"], "")
        self.assertEqual(config["proxy_defaults"]["provider_proxy"], "")
        self.assertTrue(config["proxy_defaults"]["all_no_proxy"])
        self.assertFalse(config["proxy_defaults"]["all_jp_proxy"])

    def test_local_ui_config_exposes_local_proxy_defaults(self) -> None:
        original_proxy = app.LOCAL_UI_PROXY
        app.LOCAL_UI_PROXY = "http://user-region-JP:pass@127.0.0.1:3010"
        try:
            config = app.build_ui_config("local")
        finally:
            app.LOCAL_UI_PROXY = original_proxy

        self.assertEqual(config["profile"], "local")
        self.assertTrue(config["expose_proxy_controls"])
        self.assertTrue(config["proxy_defaults"]["quick_proxy"])
        self.assertIn("region-JP", config["proxy_defaults"]["checkout_proxy"])
        self.assertIn("region-JP", config["proxy_defaults"]["provider_proxy"])
        self.assertTrue(config["proxy_defaults"]["all_jp_proxy"])
        self.assertFalse(config["proxy_defaults"]["all_no_proxy"])
        self.assertTrue(any("region-US" in item for item in config["proxy_presets"]))


if __name__ == "__main__":
    unittest.main()
