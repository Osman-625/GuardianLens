import unittest

from url_utils import normalize_listing_url, normalize_mudah_listing_url


class ListingUrlTests(unittest.TestCase):
    def test_relative_listing(self):
        self.assertEqual(
            normalize_listing_url("/p/headphone-1455931388/"),
            "https://www.carousell.com.my/p/headphone-1455931388/",
        )

    def test_query_removed(self):
        self.assertEqual(
            normalize_listing_url("https://www.carousell.com.my/p/item-name-1234567890/?t-id=abc"),
            "https://www.carousell.com.my/p/item-name-1234567890/",
        )

    def test_non_listing_rejected(self):
        self.assertIsNone(normalize_listing_url("https://www.carousell.com.my/categories/audio-595/"))
        self.assertIsNone(normalize_listing_url("https://example.com/p/test-123/"))


class MudahListingUrlTests(unittest.TestCase):
    def test_relative_listing(self):
        self.assertEqual(
            normalize_mudah_listing_url("/used-iphone-15-black-256gb-115391385.htm"),
            "https://www.mudah.my/used-iphone-15-black-256gb-115391385.htm",
        )

    def test_query_removed(self):
        self.assertEqual(
            normalize_mudah_listing_url("https://www.mudah.my/iphone-17-pro-max-256gb-115617580.htm?ref=abc"),
            "https://www.mudah.my/iphone-17-pro-max-256gb-115617580.htm",
        )

    def test_non_listing_rejected(self):
        self.assertIsNone(
            normalize_mudah_listing_url("https://www.mudah.my/malaysia/mobile-phones-and-gadgets-for-sale")
        )
        self.assertIsNone(normalize_mudah_listing_url("https://example.com/item-123.htm"))


if __name__ == "__main__":
    unittest.main()
