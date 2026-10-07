import unittest

from tme3bot.chat_refs import (
    normalize_bot_api_chat_ref,
    normalize_peer_identity,
    normalize_tdl_chat_ref,
)


class ChatReferenceTests(unittest.TestCase):
    def test_normalizes_all_tdl_reference_forms(self):
        values = {
            "@IYear": "iyear",
            "iyear": "iyear",
            "123456789": "123456789",
            "https://t.me/IYear": "iyear",
            "+1 123456789": "+1123456789",
        }
        for raw, expected in values.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_tdl_chat_ref(raw), expected)

    def test_rejects_non_tdl_chat_references(self):
        for raw in ("", "https://example.com/iyear", "t.me/iyear", "+1 23"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                normalize_tdl_chat_ref(raw)

    def test_bot_api_destinations_accept_ids_and_public_usernames_but_not_phones(self):
        self.assertEqual(normalize_bot_api_chat_ref("123456789"), "123456789")
        self.assertEqual(normalize_bot_api_chat_ref("iyear"), "@iyear")
        self.assertEqual(normalize_bot_api_chat_ref("https://t.me/IYear"), "@iyear")
        self.assertEqual(normalize_bot_api_chat_ref("https://t.me/c/123456789/12"), "-100123456789")
        with self.assertRaisesRegex(ValueError, "tidak dapat mengirim ke nomor telepon"):
            normalize_bot_api_chat_ref("+1 123456789")

    def test_normalizes_verified_peer_identity(self):
        self.assertEqual(normalize_peer_identity("Channel", "00123"), ("channel", "123"))
        self.assertEqual(normalize_peer_identity("basic_group", -123), ("basic_group", "-123"))
        for peer_type, peer_id in (("", "1"), ("channel/type", "1"), ("user", "0"), ("user", "abc")):
            with self.subTest(peer_type=peer_type, peer_id=peer_id), self.assertRaises(ValueError):
                normalize_peer_identity(peer_type, peer_id)


if __name__ == "__main__":
    unittest.main()
