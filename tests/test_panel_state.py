import unittest

from tme3bot.frontend.telegram.panel_state import PanelViewStore


class PanelViewStoreTests(unittest.TestCase):
    def test_new_view_invalidates_previous_async_owner(self) -> None:
        views = PanelViewStore()

        download_token = views.begin(10)
        self.assertTrue(views.is_active(10, download_token))

        views.invalidate(10)
        self.assertFalse(views.is_active(10, download_token))

        export_token = views.begin(10)
        self.assertTrue(views.is_active(10, export_token))
        self.assertFalse(views.is_active(10, download_token))

    def test_tokens_are_scoped_per_chat(self) -> None:
        views = PanelViewStore()
        first = views.begin(10)
        second = views.begin(20)

        views.invalidate(10)

        self.assertFalse(views.is_active(10, first))
        self.assertTrue(views.is_active(20, second))
        self.assertTrue(views.is_active(20, None))


if __name__ == "__main__":
    unittest.main()
