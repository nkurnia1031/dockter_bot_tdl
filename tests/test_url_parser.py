import unittest

from tme3bot.url_parser import URLParseError, parse_tme3_url


class ParseTme3UrlTests(unittest.TestCase):
    def test_parses_full_url_with_label(self) -> None:
        parsed = parse_tme3_url("https://t.me3/c/@KFCMNB_bot/3/1langs", "t.me3")
        self.assertEqual(parsed.chat_ref, "@KFCMNB_bot")
        self.assertEqual(parsed.bootstrap_message_id, 3)
        self.assertEqual(parsed.requested_label, "1langs")
        self.assertEqual(parsed.canonical_label, "1langs")

    def test_missing_label_falls_back_to_slugified_chat_ref(self) -> None:
        parsed = parse_tme3_url("https://t.me3/c/@KFCMNB_bot/3", "t.me3")
        self.assertEqual(parsed.canonical_label, "kfcmnb_bot")
        self.assertIsNone(parsed.requested_label)

    def test_accepts_normal_t_me_private_chat_url(self) -> None:
        parsed = parse_tme3_url("https://t.me/c/4429689667/12", "t.me3")
        self.assertEqual(parsed.chat_ref, "4429689667")
        self.assertEqual(parsed.bootstrap_message_id, 12)
        self.assertIsNone(parsed.requested_label)

    def test_rejects_other_host(self) -> None:
        with self.assertRaises(URLParseError):
            parse_tme3_url("https://example.com/c/@KFCMNB_bot/3", "t.me3")

    def test_rejects_invalid_shape(self) -> None:
        with self.assertRaises(URLParseError):
            parse_tme3_url("https://t.me3/@KFCMNB_bot/3/1langs", "t.me3")


if __name__ == "__main__":
    unittest.main()
