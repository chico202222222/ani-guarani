"""Offline regression tests: no HTTP requests, Firefox or Snap processes."""
import unittest
from threading import Event
from unittest.mock import MagicMock, call, patch

import requests
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By

from plugins import animesonlinecc, utils


class ParsingTests(unittest.TestCase):
    def setUp(self):
        self.http = self.enterContext(patch.object(
            utils.requests, "get", side_effect=AssertionError("Unexpected network request")
        ))


    def test_animesonlinecc_titles_urls_and_seasons(self):
        html = '''
            <div class="data"><h3>Missing link</h3></div>
            <div class="data"><h3><a href="../first"> First </a></h3></div>
            <div class="data"><a href="/ignored">Missing h3</a></div>
            <div class="data"><h3><a href=" ">Empty URL</a></h3></div>
            <div class="data"><h3><a href="/empty-title"> </a></h3></div>
            <div class="data"><h3><a href="//cdn.example/second">Second</a></h3></div>
        '''
        pages = [
            (html, "https://redirect.example/search/"),
            ('<div class="se-c"></div><div class="se-c"></div>', "https://redirect.example/first"),
            ('<div class="se-c"></div>', "https://cdn.example/second"),
        ]
        with patch.object(animesonlinecc, "fetch_page", side_effect=pages) as fetch, patch.object(animesonlinecc, "rep") as rep:
            animesonlinecc.AnimesOnlineCC.search_anime("test")
        self.assertEqual(rep.add_anime.call_args_list, [
            call("First", "https://redirect.example/first", "animesonlinecc"),
            call("Second", "https://cdn.example/second", "animesonlinecc"),
            call("First Season 2", "https://redirect.example/first", "animesonlinecc", 2),
        ])
        self.assertEqual(fetch.call_args_list[1:], [
            call("https://redirect.example/first"), call("https://cdn.example/second"),
        ])

    def test_search_query_quoting_preserves_site_separators(self):
        cases = [

            (animesonlinecc, animesonlinecc.AnimesOnlineCC, "https://animesonlinecc.to/search/a%2Bb+%2F%3F%23+%25+a%C3%A7%C3%A3o"),
        ]
        for module, plugin, expected in cases:
            with self.subTest(source=plugin.name), patch.object(module, "fetch_page", return_value=("", expected)) as fetch, patch.object(module, "rep"):
                plugin.search_anime("  a+b  /?# % ação  ")
                fetch.assert_called_once_with(expected)

    def test_episode_titles_and_relative_urls_remain_aligned(self):
        anchors = '''
            <a {attrs}>Missing URL</a>
            <a {attrs} href="../ep1?x=1&amp;y=2"> Episode 1 </a>
            <a {attrs} href="/empty"> </a>
            <a {attrs} href=" ">Empty URL</a>
            <a {attrs} href="//cdn.example/ep2">Episode 2</a>
        '''

        cc_html = '<ul class="episodios">' + ''.join(
            f'<div class="episodiotitle">{line}</div>'
            for line in anchors.format(attrs="").splitlines()
        ) + '</ul>'
        for module, plugin, html in (

            (animesonlinecc, animesonlinecc.AnimesOnlineCC, cc_html),
        ):
            with self.subTest(source=plugin.name), patch.object(module, "fetch_page", return_value=(html, "https://redirect.example/anime/")), patch.object(module, "rep") as rep:
                plugin.search_episodes("Anime", "https://original.example/anime", None)
                rep.add_episode_list.assert_called_once_with(
                    "Anime", ["Episode 1", "Episode 2"],
                    ["https://redirect.example/ep1?x=1&y=2", "https://cdn.example/ep2"], plugin.name,
                )


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.response = MagicMock()
        self.response.__enter__.return_value = self.response
        self.get = self.enterContext(patch.object(utils.requests, "get", return_value=self.response))
        self.url = "https://example.org/request"

    def test_timeout_status_redirect_base_and_response_cleanup(self):
        self.response.text = "HTML"
        self.response.url = "https://example.org/redirected/"
        self.assertEqual(utils.fetch_page(self.url), ("HTML", self.response.url))
        self.get.assert_called_once_with(self.url, timeout=(5, 20))
        self.response.raise_for_status.assert_called_once_with()
        self.response.__exit__.assert_called_once()

    def test_http_failure_is_descriptive_and_closes_response(self):
        error = requests.HTTPError("503 Service Unavailable")
        self.response.raise_for_status.side_effect = error
        with self.assertRaisesRegex(RuntimeError, "Failed to fetch.*example.org/request.*503") as caught:
            utils.fetch_page(self.url)
        self.assertIs(caught.exception.__cause__, error)
        self.response.__exit__.assert_called_once()

    def test_connection_and_read_timeouts_preserve_cause(self):
        for error in (requests.ConnectTimeout("connect"), requests.ReadTimeout("read")):
            with self.subTest(error=type(error).__name__):
                self.get.side_effect = error
                with self.assertRaisesRegex(RuntimeError, "Failed to fetch.*example.org/request") as caught:
                    utils.fetch_page(self.url)
                self.assertIs(caught.exception.__cause__, error)


class PlayerTests(unittest.TestCase):
    def setUp(self):
        self.firefox = self.enterContext(patch.object(utils.webdriver, "Firefox"))
        self.enterContext(patch.object(utils, "is_firefox_installed_as_snap", return_value=False))
        self.wait = self.enterContext(patch.object(utils, "WebDriverWait"))
        self.driver = self.firefox.return_value
        self.driver.current_url = "https://redirect.example/episode/"
        self.element = MagicMock()
        self.element.get_property.return_value = "../player?x=1&y=2"
        self.wait.return_value.until.return_value = [self.element]
        self.event = Event()
        self.container = []
        self.url = "https://example.org/episode"

    def search(self, plugin=None):
        if plugin is not None:
            plugin.search_player_src(self.url, self.container, self.event)
        else:
            utils.find_player_src(self.url, self.container, self.event, "testsource", (
                (By.CSS_SELECTOR, "video"), (By.CSS_SELECTOR, "iframe"),
            ))

    def test_success_resolves_src_sets_event_and_closes_firefox(self):
        self.search()
        self.assertEqual(self.container, ["https://redirect.example/player?x=1&y=2"])
        self.assertTrue(self.event.is_set())
        self.element.get_property.assert_called_once_with("src")
        self.driver.get.assert_called_once_with(self.url)
        self.driver.set_page_load_timeout.assert_called_once_with(30)
        self.driver.set_script_timeout.assert_called_once_with(30)
        self.wait.assert_called_once_with(self.driver, 7)
        self.driver.quit.assert_called_once_with()

    def test_generic_player_falls_back_to_iframe_selector(self):
        self.wait.return_value.until.side_effect = [TimeoutException("video missing"), [self.element]]
        with patch.object(utils.EC, "visibility_of_all_elements_located") as visible:
            self.search()
        self.assertEqual(visible.call_args_list, [
            call((By.CSS_SELECTOR, "video")),
            call((By.CSS_SELECTOR, "iframe")),
        ])
        self.assertEqual(len(self.container), 1)
        self.driver.quit.assert_called_once_with()

    def test_animesonlinecc_keeps_iframe_url_without_claiming_stream(self):
        self.element.get_property.return_value = "https://example.org/embed/player.html"
        with patch.object(utils.EC, "visibility_of_all_elements_located") as visible:
            self.search(animesonlinecc.AnimesOnlineCC)
        visible.assert_called_once_with((By.XPATH, "/html/body/div[1]/div[2]/div[2]/div[2]/div[1]/div[1]/div[1]/iframe"))
        self.assertEqual(self.container, ["https://example.org/embed/player.html"])
        self.driver.quit.assert_called_once_with()

    def test_unavailable_blogger_does_not_publish_or_cancel(self):
        self.element.get_property.return_value = "https://www.blogger.com/video.g?token=test"
        html = '<main><div class="Phuhlc">Video is unavailable</div></main>'
        with patch.object(utils, "fetch_page", return_value=(html, self.element.get_property.return_value)), self.assertLogs(utils.logger, level="WARNING"):
            with self.assertRaisesRegex(RuntimeError, "este vídeo está indisponível"):
                self.search(animesonlinecc.AnimesOnlineCC)
        self.assertEqual(self.container, [])
        self.assertFalse(self.event.is_set())
        self.driver.quit.assert_called_once_with()

    def test_unavailable_blogger_falls_back_to_other_selector(self):
        self.element.get_property.side_effect = ["https://www.blogger.com/video.g?token=test", "https://example.org/video.mp4"]
        with patch.object(utils, "fetch_page", return_value=('<main><div class="Phuhlc">Video is unavailable</div></main>', "https://www.blogger.com/")), self.assertLogs(utils.logger, level="WARNING"):
            self.search()
        self.assertEqual(self.container, ["https://example.org/video.mp4"])
        self.assertTrue(self.event.is_set())

    def test_blogger_without_explicit_unavailable_message_is_not_rejected(self):
        with patch.object(utils, "fetch_page", return_value=('<script>var VIDEO_CONFIG = {}</script>', "https://www.blogger.com/")) as fetch:
            self.assertEqual(utils.resolve_blogger_player("https://www.blogger.com/video.g?token=test"), "https://www.blogger.com/video.g?token=test")
        fetch.assert_called_once()

    def test_other_hosts_are_not_fetched(self):
        with patch.object(utils, "fetch_page") as fetch:
            utils.resolve_blogger_player("https://example.org/video.g?token=test")
            utils.resolve_blogger_player("https://www.blogger.com.evil.example/video.g?token=test")
        fetch.assert_not_called()

    def test_navigation_timeout_closes_firefox_and_preserves_cause(self):
        error = TimeoutException("navigation timed out")
        self.driver.get.side_effect = error
        with self.assertRaisesRegex(RuntimeError, "Failed to inspect player.*testsource.*example.org/episode") as caught:
            self.search()
        self.assertIs(caught.exception.__cause__, error)
        self.driver.quit.assert_called_once_with()
        self.assertEqual(self.container, [])
        self.assertFalse(self.event.is_set())

    def test_missing_players_close_firefox(self):
        self.wait.return_value.until.side_effect = TimeoutException("missing")
        with self.assertRaisesRegex(RuntimeError, "No visible player found in testsource"):
            self.search()
        self.assertEqual(self.wait.call_count, 2)
        self.driver.quit.assert_called_once_with()
        self.assertEqual(self.container, [])
        self.assertFalse(self.event.is_set())

    def test_empty_src_closes_firefox_without_publishing(self):
        self.element.get_property.return_value = " "
        with self.assertRaisesRegex(RuntimeError, "valid HTTP"):
            self.search()
        self.driver.quit.assert_called_once_with()
        self.assertEqual(self.container, [])
        self.assertFalse(self.event.is_set())

    def test_invalid_src_does_not_publish_or_cancel(self):
        for src in ("blob:https://example.org/id", "javascript:alert(1)",
                    "file:///tmp/video", "http://", "https://[broken", None):
            with self.subTest(src=src):
                self.element.get_property.return_value = src
                with self.assertRaisesRegex(RuntimeError, "valid HTTP"):
                    self.search()
                self.assertEqual(self.container, [])
                self.assertFalse(self.event.is_set())
        self.assertEqual(self.driver.quit.call_count, 6)

    def test_empty_or_invalid_src_falls_back_to_valid_player(self):
        for src in (" ", "blob:https://example.org/id", "https://[broken"):
            with self.subTest(src=src):
                self.event.clear()
                self.container.clear()
                self.element.get_property.side_effect = [src, "https://example.org/player"]
                self.search()
                self.assertEqual(self.container, ["https://example.org/player"])
                self.assertTrue(self.event.is_set())
        self.assertEqual(self.driver.quit.call_count, 3)

    def test_src_read_failure_closes_firefox(self):
        self.element.get_property.side_effect = WebDriverException("stale element")
        with self.assertRaisesRegex(RuntimeError, "Failed to inspect player"):
            self.search()
        self.driver.quit.assert_called_once_with()

    def test_cleanup_failure_does_not_mask_navigation_error(self):
        error = TimeoutException("navigation")
        self.driver.get.side_effect = error
        self.driver.quit.side_effect = WebDriverException("cleanup")
        with self.assertLogs(utils.logger, level="WARNING") as logs:
            with self.assertRaises(RuntimeError) as caught:
                self.search()
        self.assertIs(caught.exception.__cause__, error)
        self.assertIn("Failed to close Firefox", logs.output[0])

    def test_already_cancelled_does_not_start_firefox(self):
        self.event.set()
        self.search()
        self.firefox.assert_not_called()
        self.assertEqual(self.container, [])

    def test_cancellation_after_start_closes_firefox_before_navigation(self):
        self.driver.set_script_timeout.side_effect = lambda timeout: self.event.set()
        self.search()
        self.driver.get.assert_not_called()
        self.driver.quit.assert_called_once_with()
        self.assertEqual(self.container, [])

    def test_cancellation_during_wait_short_circuits_condition_and_closes(self):
        def cancel_during_wait(predicate):
            self.event.set()
            self.assertTrue(predicate(self.driver))
            return True

        self.wait.return_value.until.side_effect = cancel_during_wait
        with patch.object(utils.EC, "visibility_of_all_elements_located") as visible:
            self.search()
            visible.return_value.assert_not_called()
        self.element.get_property.assert_not_called()
        self.driver.quit.assert_called_once_with()
        self.assertEqual(self.container, [])

    def test_cancellation_before_publish_keeps_worker_container_empty(self):
        def cancel_while_reading_src(name):
            self.event.set()
            return "https://example.org/player"

        self.element.get_property.side_effect = cancel_while_reading_src
        self.search()
        self.driver.quit.assert_called_once_with()
        self.assertEqual(self.container, [])


if __name__ == "__main__":
    unittest.main()
