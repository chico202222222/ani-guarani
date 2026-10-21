import html
import json
import unittest
from unittest.mock import patch

from plugins.utils import resolve_blogger_player


class BloggerTests(unittest.TestCase):
    url = "https://www.blogger.com/video.g?token=example"
    media = "https://rr1---example.googlevideo.com/videoplayback?itag=18&sig=a=b"

    def page(self, urls):
        data = [None, None, None, None, self.url, [None], None,
                [1, None, [[url, [18]] for url in urls]], True]
        payload = "%.@." + json.dumps(data, ensure_ascii=True)[1:]
        return '<c-wiz data-p="' + html.escape(payload, quote=True) + '"></c-wiz>'

    def test_new_layout_resolves_structured_stream_and_preserves_query(self):
        page = self.page([self.media])
        with patch("plugins.utils.fetch_page", return_value=(page, self.url)):
            self.assertEqual(resolve_blogger_player(self.url), self.media)

    def test_unicode_escaped_query_is_decoded_by_json(self):
        page = self.page([self.media]).replace("&amp;", r"\u0026").replace("itag=", r"itag\u003d")
        with patch("plugins.utils.fetch_page", return_value=(page, self.url)):
            self.assertEqual(resolve_blogger_player(self.url), self.media)

    def test_untrusted_or_non_media_urls_are_not_used(self):
        for invalid in ("file:///tmp/video", "https://evil.example/videoplayback",
                        "https://googlevideo.com.evil.example/videoplayback",
                        "https://cdn.googlevideo.com/not-a-video"):
            with self.subTest(invalid=invalid), patch("plugins.utils.fetch_page", return_value=(self.page([invalid]), self.url)):
                self.assertEqual(resolve_blogger_player(self.url), self.url)

    def test_legacy_and_malformed_payloads_keep_extractor_fallback(self):
        for page in ('<script>var VIDEO_CONFIG = {}</script>', '<c-wiz data-p="%.@.broken"></c-wiz>'):
            with self.subTest(page=page), patch("plugins.utils.fetch_page", return_value=(page, self.url)):
                self.assertEqual(resolve_blogger_player(self.url), self.url)

    def test_skips_invalid_stream_and_finds_next(self):
        with patch("plugins.utils.fetch_page", return_value=(self.page(["javascript:alert(1)", self.media]), self.url)):
            self.assertEqual(resolve_blogger_player(self.url), self.media)


if __name__ == "__main__":
    unittest.main()


class BloggerItagRankTests(unittest.TestCase):
    def test_prefers_mp4_over_3gpp(self):
        from plugins.utils import _itag_rank
        base = "https://rr1.googlevideo.com/videoplayback?itag="
        urls = [base + "13", base + "18", base + "17"]
        self.assertEqual(max(urls, key=_itag_rank), base + "18")
