import unittest
from unittest.mock import patch

from tme3bot.channel_ref import channel_chat_id, channel_tdl_ref, compact_channel_ref


class ChannelRefTests(unittest.TestCase):
    def test_link_and_compact_id_share_one_canonical_value(self):
        self.assertEqual(compact_channel_ref("https://t.me/c/1588718424/14"), "1588718424")
        self.assertEqual(channel_chat_id("1588718424"), -1001588718424)
        self.assertEqual(channel_tdl_ref("-1001588718424"), "-1001588718424")

    def test_app_config_accepts_one_compact_storage_and_backup_value(self):
        from tme3bot.config import AppConfig
        with patch.dict("os.environ", {
            "APP_ROLE": "backend", "BOT_TOKEN": "token",
            "STORAGE_CHANNEL": "https://t.me/c/1588718424/14",
            "BACKUP_CHANNEL": "9876543210",
        }, clear=False):
            config = AppConfig.from_env()
        self.assertEqual(config.storage_channel_ref, "-1001588718424")
        self.assertEqual(config.storage_channel_id, -1001588718424)
        self.assertEqual(config.storage_channel, "1588718424")
        self.assertEqual(config.backup_channel_id, -1009876543210)


if __name__ == "__main__":
    unittest.main()
