"""AnimesDigital, AniTube e o player api.anivideo.net: tudo offline."""
import unittest
from threading import Event
from unittest.mock import MagicMock, patch

import requests

from plugins import animesdigital, anitube, utils
from plugins.animesdigital import AnimesDigital
from plugins.anitube import AniTube
from repository import Repository

M3U8 = "https://cdn.example/stream/j/jujutsu-kaisen/01.mp4/index.m3u8"
PLAYER = "https://api.anivideo.net/videohls.php?d=" + M3U8 + "&nocache1"


def reply(status):
    result = MagicMock()
    result.__enter__.return_value = result
    result.status_code = status
    return result


class UtilsTests(unittest.TestCase):
    def test_anivideo_stream_extracts_d_parameter(self):
        self.assertEqual(utils.anivideo_stream(PLAYER), M3U8)

    def test_anivideo_stream_rejects_other_hosts_and_bad_values(self):
        for url in ("https://evil.example/videohls.php?d=" + M3U8,
                    "https://api.anivideo.net/other.php?d=" + M3U8,
                    "https://api.anivideo.net/videohls.php",
                    "https://api.anivideo.net/videohls.php?d=javascript:alert(1)",
                    "https://api.anivideo.net/videohls.php?d=file:///etc/passwd",
                    "https://[bad"):
            with self.subTest(url=url):
                self.assertIsNone(utils.anivideo_stream(url))

    def test_media_alive_classifies_status(self):
        for status, expected in ((200, True), (206, True), (301, True), (403, False),
                                 (404, False), (410, False), (500, None), (429, None)):
            with self.subTest(status=status), patch.object(utils.requests, "get", return_value=reply(status)) as get:
                self.assertIs(utils.media_alive("https://x.example/v.mp4", {"Referer": "r"}), expected)
                self.assertEqual(get.call_args.kwargs["headers"], {"Range": "bytes=0-0", "Referer": "r"})
                self.assertFalse(get.call_args.kwargs["allow_redirects"])

    def test_media_alive_network_error_is_undetermined(self):
        with patch.object(utils.requests, "get", side_effect=requests.ConnectionError):
            self.assertIsNone(utils.media_alive("https://x.example/v.mp4"))

    def find(self, html, alive):
        container, event = [], Event()
        with patch.object(utils, "fetch_page", return_value=(html, "https://site.example/ep")), \
                patch.object(utils, "media_alive", side_effect=alive):
            utils.find_anivideo_src("https://site.example/ep", container, event, "Fonte")
        return container, event

    def test_find_picks_live_player_and_ignores_other_iframes(self):
        html = f'<iframe src="https://ads.example/x"></iframe><iframe src="{PLAYER}"></iframe>'
        container, event = self.find(html, [True])
        self.assertEqual(container, [M3U8])
        self.assertTrue(event.is_set())

    def test_find_dead_cdn_raises_and_publishes_nothing(self):
        with self.assertRaisesRegex(RuntimeError, "Fonte: o vídeo não existe mais"):
            self.find(f'<iframe src="{PLAYER}"></iframe>', [False])

    def test_find_undetermined_cdn_still_publishes(self):
        container, _ = self.find(f'<iframe src="{PLAYER}"></iframe>', [None])
        self.assertEqual(container, [M3U8])

    def test_find_without_player_raises(self):
        with self.assertRaisesRegex(RuntimeError, "nenhum player"):
            self.find("<p>nada</p>", [])


def item(href, title, tag=None):
    badge = f'<div class="aniCC">{tag}</div>' if tag else ""
    return (f'<div class="aniItem"><a href="{href}" title="{title}"><div class="aniItemImg">{badge}</div>'
            f'<div class="aniItemNome"> {title} </div></a></div>')


class AniTubeTests(unittest.TestCase):
    def setUp(self):
        self.rep = Repository()
        self.enterContext(patch.object(anitube, "rep", self.rep))

    def test_search_uses_card_tag_and_strips_suffix(self):
        html = (item("/video/1/", "Jujutsu Kaisen – Todos os Episódios", "Legendado")
                + item("/970b/", "Jujutsu Kaisen (Dublado) – Todos os Episódios", "Dublado")
                + item("/video/3/", "Jujutsu Kaisen: Filme", "Filme")
                + '<div class="aniItem"><a>sem nome</a></div>')
        with patch.object(anitube, "fetch_page", return_value=(html, "https://www.anitube.zip/?s=x")) as fetch:
            AniTube.search_anime("jujutsu kaisen")
        fetch.assert_called_once_with("https://www.anitube.zip/?s=jujutsu+kaisen", anitube.HEADERS)
        self.assertEqual(self.rep.anime_to_urls["Jujutsu Kaisen [AniTube]"],
                         [("https://www.anitube.zip/video/1/", "anitube", None)])
        self.assertEqual(self.rep.anime_audio["Jujutsu Kaisen [AniTube]"], {"legendado"})
        self.assertEqual(self.rep.anime_audio["Jujutsu Kaisen (Dublado) [AniTube]"], {"dublado"})
        self.assertEqual(self.rep.anime_audio["Jujutsu Kaisen: Filme [AniTube]"], {"legendado"})

    def test_card_tag_overrides_misleading_title(self):
        html = item("/a/", "Naruto", "Dublado")
        with patch.object(anitube, "fetch_page", return_value=(html, "https://www.anitube.zip/")):
            AniTube.search_anime("naruto")
        self.assertEqual(self.rep.anime_audio["Naruto [AniTube]"], {"dublado"})

    def test_episodes_keep_site_order_and_drop_duplicates(self):
        html = ('<a href="/menu">Menu</a><div class="pagAniListaContainer">'
                '<a href="/ep1/">Ep 01</a><a href="https://www.anitube.zip/ep2/">Ep 02</a>'
                '<a href="/ep1/">Ep 01</a><a href="/vazio/"> </a></div>')
        with patch.object(anitube, "fetch_page", return_value=(html, "https://www.anitube.zip/a/")):
            AniTube.search_episodes("Anime", "https://www.anitube.zip/a/", None)
        self.assertEqual(self.rep.get_episode_list("Anime"), ["Ep 01", "Ep 02"])
        self.assertEqual(self.rep.anime_episodes_urls["Anime"],
                         [(["https://www.anitube.zip/ep1/", "https://www.anitube.zip/ep2/"], "anitube")])

    def test_movie_page_is_its_own_episode(self):
        html = f'<iframe src="{PLAYER}"></iframe>'
        with patch.object(anitube, "fetch_page", return_value=(html, "https://www.anitube.zip/video/9/")):
            AniTube.search_episodes("Filme", "https://www.anitube.zip/video/9/", None)
        self.assertEqual(self.rep.anime_episodes_urls["Filme"],
                         [(["https://www.anitube.zip/video/9/"], "anitube")])

    def test_page_without_episodes_or_player_fails(self):
        with patch.object(anitube, "fetch_page", return_value=("<p/>", "https://www.anitube.zip/")):
            with self.assertRaisesRegex(RuntimeError, "nenhum episódio"):
                AniTube.search_episodes("Anime", "https://www.anitube.zip/", None)


def card(href, label):
    return (f'<div class="item_ep"><a class="b_flex" href="{href}"><div class="dados"><div class="left">'
            f'<div class="title_anime">{label}</div><div class="date">5 anos atrás</div></div></div></a></div>')


class AnimesDigitalTests(unittest.TestCase):
    ROOT = "https://animesdigital.org/anime/a/jjk"

    def setUp(self):
        self.rep = Repository()
        self.enterContext(patch.object(animesdigital, "rep", self.rep))

    def test_search_reads_cards_and_audio_from_title(self):
        html = ('<div class="itemA"><a href="/anime/a/jjk"><span class="title_anime">Jujutsu Kaisen</span></a></div>'
                '<div class="itemA"><a href="/anime/a/jjk-dub"><span class="title_anime">Jujutsu Kaisen Dublado</span></a></div>'
                '<div class="itemA"><a href="/x"></a></div>')
        with patch.object(animesdigital, "fetch_page", return_value=(html, "https://animesdigital.org/pesquisa/jujutsu/")) as fetch:
            AnimesDigital.search_anime(" jujutsu kaisen ")
        fetch.assert_called_once_with("https://animesdigital.org/?s=jujutsu+kaisen", animesdigital.HEADERS)
        self.assertEqual(self.rep.anime_to_urls["Jujutsu Kaisen [AnimesDigital]"],
                         [("https://animesdigital.org/anime/a/jjk", "animesdigital", None)])
        self.assertEqual(self.rep.anime_audio["Jujutsu Kaisen Dublado [AnimesDigital]"], {"dublado"})

    def test_episodes_sorted_ascending_across_pages(self):
        pagination = ('<ul class="content-pagination"><li><a href="%s/">1</a></li>'
                      '<li><a href="%s/page/2/">2</a></li></ul>' % (self.ROOT, self.ROOT))
        page1 = card("/video/a/3", "Jujutsu Kaisen Episódio 3") + card("/video/a/2", "Jujutsu Kaisen Episódio 2") + pagination
        page2 = card("/video/a/1", "Jujutsu Kaisen Episódio 1") + card("/video/a/25", "Jujutsu Kaisen Episódio 2.5")
        pages = {self.ROOT: page1, self.ROOT + "/page/2/": page2}
        fetch = lambda url, headers=None: (pages[url], url)
        with patch.object(animesdigital, "fetch_page", side_effect=fetch):
            AnimesDigital.search_episodes("Anime", self.ROOT, None)
        self.assertEqual(self.rep.get_episode_list("Anime"),
                         ["Episódio 1", "Episódio 2", "Episódio 2.5", "Episódio 3"])
        self.assertEqual([url.rsplit("/", 1)[-1] for url in self.rep.anime_episodes_urls["Anime"][0][0]],
                         ["1", "2", "25", "3"])

    def test_unnumbered_entries_go_last_with_their_own_label(self):
        html = card("/video/a/f", "Jujutsu Kaisen Filme") + card("/video/a/1", "Jujutsu Kaisen Episódio 1")
        with patch.object(animesdigital, "fetch_page", return_value=(html, self.ROOT)):
            AnimesDigital.search_episodes("Anime", self.ROOT, None)
        self.assertEqual(self.rep.get_episode_list("Anime"), ["Episódio 1", "Jujutsu Kaisen Filme"])

    def test_no_episodes_is_an_error(self):
        with patch.object(animesdigital, "fetch_page", return_value=("<p/>", self.ROOT)):
            with self.assertRaisesRegex(RuntimeError, "nenhum episódio"):
                AnimesDigital.search_episodes("Anime", self.ROOT, None)


if __name__ == "__main__":
    unittest.main()
