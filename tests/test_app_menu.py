import unittest

from tme3bot.frontend.telegram.text import source_digest


class AppMenuTests(unittest.TestCase):
    def test_source_digest_is_short_callback_safe(self) -> None:
        self.assertEqual(len(source_digest("@bot")), 12)
        self.assertEqual(source_digest("@bot"), source_digest("@bot"))


if __name__ == "__main__":
    unittest.main()
