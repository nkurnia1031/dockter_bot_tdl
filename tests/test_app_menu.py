import unittest

from tme3bot.bot_text import build_tme3_url, source_digest


class AppMenuTests(unittest.TestCase):
    def test_build_tme3_url_encodes_optional_label(self) -> None:
        self.assertEqual(build_tme3_url("t.me3", "@bot", 12), "https://t.me3/c/@bot/12")
        self.assertEqual(
            build_tme3_url("t.me3", "@bot", 12, "my label"),
            "https://t.me3/c/@bot/12/my%20label",
        )

    def test_source_digest_is_short_callback_safe(self) -> None:
        self.assertEqual(len(source_digest("@bot")), 12)
        self.assertEqual(source_digest("@bot"), source_digest("@bot"))


if __name__ == "__main__":
    unittest.main()
