# SPDX-License-Identifier: Apache-2.0

import json
import unittest
from html import escape
from threading import Event
from unittest.mock import MagicMock, call, patch
from urllib.parse import urlencode

import requests

from plugins import animesonlinecloud as cloud
from plugins.animesonlinecloud import AnimesOnlineCloud
from repository import Repository

BASE = "https://animesonline.cloud"
ANIME = BASE + "/anime/naruto"
EPISODE = BASE + "/episodio/naruto-episodio-01"
MEDIA = "https://aniplay.online/Midias/Animes/Letra-J/Jujutsu-Kaisen-3/Dub/01.mp4"
BLOGGER = "https://www.blogger.com/video.g?token=example"
GOOGLEVIDEO = "https://rr1.googlevideo.com/videoplayback?token=a%2Bb&sig=x=y"
OPTION = '<li data-post="42" data-type="tv" data-nume="1"><span class="title">HD</span></li>'
PLAYER = '<ul id="playeroptionsul">' + OPTION + '</ul>'
ENDPOINT = BASE + "/wp-json/dooplayer/v2/42/tv/1"


def response(html="", url=EPISODE, status=200, headers=None, payload=None):
    result = MagicMock()
    result.__enter__.return_value = result
    result.text = html
    result.url = url
    result.status_code = status
    result.headers = headers or {}
    result.json.return_value = payload
    if status >= 400:
        result.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status}")
    return result


def result(title, href):
    return ('<div class="result-item"><div class="title"><a href="'
            + escape(href, quote=True) + '">' + escape(title) + '</a></div></div>')


def pagination(href, attribute='rel="next"'):
    return '<div class="pagination"><a ' + attribute + ' href="' + escape(href, quote=True) + '">Next</a></div>'


def card(number, title, slug, visible="Visible title"):
    return (f'<div class="episode-card" data-episode-number="{escape(str(number), quote=True)}" '
            f'data-episode-title="{escape(title, quote=True)}"><a href="/episodio/{slug}">'
            f'<span class="episode-title">{escape(visible)}</span></a></div>')


def season(number, content):
    return f'<div class="se-c"><div class="se-q"><span class="se-t">{number}</span></div>{content}</div>'


def seasons(content):
    return '<div id="seasons">' + content + '</div>'


def legacy(number, title, slug):
    return (f'<li><div class="numerando">{number}</div><div class="episodiotitle">'
            f'<a href="/episodio/{slug}">{title}</a></div></li>')


class AnimesOnlineCloudTests(unittest.TestCase):
    def setUp(self):
        self.rep = Repository()
        self.enterContext(patch.object(cloud, "rep", self.rep))
        self.get = self.enterContext(patch.object(cloud.requests, "get"))
        self.blogger = self.enterContext(patch.object(cloud.utils, "resolve_blogger_player"))
        self.blogger.return_value = GOOGLEVIDEO
        self.alive = self.enterContext(patch.object(cloud.utils, "media_alive", return_value=True))
        self.event = Event()
        self.container = []

    def resolve(self, html=PLAYER, payload=None):
        self.get.side_effect = [response(html), response(payload=payload, url=ENDPOINT)]
        AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)

    def assert_not_published(self):
        self.assertEqual(self.container, [])
        self.assertFalse(self.event.is_set())

    def episode_list(self, html):
        self.get.return_value = response(html, url=ANIME)
        AnimesOnlineCloud.search_episodes("Naruto [AnimesOnlineCloud]", ANIME, None)
        titles = self.rep.get_episode_list("Naruto [AnimesOnlineCloud]")
        urls, source = self.rep.anime_episodes_urls["Naruto [AnimesOnlineCloud]"][0]
        self.assertEqual(source, "animesonlinecloud")
        return titles, urls

    def test_load_only_registers_for_pt_br(self):
        for languages in ({}, {"en": "English"}, {"pt": "Português"}):
            cloud.load(languages)
            self.assertEqual(self.rep.sources, {})
        cloud.load({"pt-br": "Português brasileiro"})
        self.assertEqual(self.rep.sources, {"animesonlinecloud": AnimesOnlineCloud})

    def test_search_card_alignment_suffix_encoding_and_request_protocol(self):
        query = "ação & aventura / 日本語?"
        search_url = BASE + "/?" + urlencode({"s": query})
        html = (result("Naruto", "/anime/naruto") + result("Outro", "/anime/outro")
                + result("Duplicate", "/anime/naruto#poster") + result("", "/anime/empty")
                + result("Bad", "javascript:alert(1)") + result("Fragment", "#poster")
                + '<div class="result-item"><div class="title">Missing link</div></div>'
                + '<a href="/anime/unrelated">Not a result</a>')
        item = response(html, url=search_url)
        self.get.return_value = item
        self.rep.add_anime("Naruto", "https://other.example/anime", "other")
        AnimesOnlineCloud.search_anime("  " + query + "  ")
        self.assertEqual(self.rep.anime_to_urls, {
            "Naruto": [("https://other.example/anime", "other", None)],
            "Naruto [AnimesOnlineCloud]": [(ANIME, "animesonlinecloud", None)],
            "Outro [AnimesOnlineCloud]": [(BASE + "/anime/outro", "animesonlinecloud", None)],
        })
        self.get.assert_called_once_with(search_url, headers={"Referer": BASE + "/"},
                                         timeout=(5, 20), allow_redirects=False)
        item.raise_for_status.assert_called_once_with()
        item.__exit__.assert_called_once()

    def test_search_retries_lowercase_when_site_returns_nothing_for_capitalized_query(self):
        self.get.side_effect = [response("<p>nada</p>", url=BASE + "/?s=Jujutsu+Kaisen"),
                                response(result("Jujutsu Kaisen", "/anime/jujutsu-kaisen"),
                                         url=BASE + "/?s=jujutsu+kaisen")]
        AnimesOnlineCloud.search_anime("Jujutsu Kaisen")
        self.assertEqual([c.args[0] for c in self.get.call_args_list],
                         [BASE + "/?s=Jujutsu+Kaisen", BASE + "/?s=jujutsu+kaisen"])
        self.assertEqual(list(self.rep.anime_to_urls), ["Jujutsu Kaisen [AnimesOnlineCloud]"])

    def test_search_does_not_retry_when_query_is_already_lowercase(self):
        self.get.return_value = response("<p>nada</p>")
        AnimesOnlineCloud.search_anime("naruto")
        self.get.assert_called_once()

    def test_search_empty_query_and_empty_results(self):
        AnimesOnlineCloud.search_anime("  ")
        self.get.assert_not_called()
        self.get.return_value = response("", url=BASE + "/?s=absent")
        AnimesOnlineCloud.search_anime("absent")
        self.assertEqual(self.rep.get_anime_titles(), [])

    def test_search_follows_only_explicit_next_and_deduplicates_pages(self):
        second, third = BASE + "/page/2/?s=Naruto", BASE + "/page/3/?s=Naruto"
        self.get.side_effect = [
            response(result("Naruto", ANIME) + pagination(second), url=BASE + "/?s=Naruto"),
            response(result("Duplicate", ANIME) + result("Outro", "/anime/outro")
                     + pagination(third, 'class="next page-numbers"'), url=second),
            response(result("Outro", "/anime/outro") + pagination("/page/4/?s=Naruto"), url=third),
        ]
        AnimesOnlineCloud.search_anime("Naruto")
        self.assertEqual([args.args[0] for args in self.get.call_args_list],
                         [BASE + "/?s=Naruto", second, third])
        self.assertEqual(self.rep.get_anime_titles(), ["Naruto [AnimesOnlineCloud]", "Outro [AnimesOnlineCloud]"])

    def test_search_does_not_follow_arbitrary_links(self):
        html = (result("Naruto", ANIME) + '<div class="pagination"><a href="/page/2/">2</a>'
                '<a class="arrow_pag" href="/page/3/">Arrow</a></div>'
                '<a rel="next" class="next" href="/unrelated">Outside pagination</a>')
        self.get.return_value = response(html, url=BASE + "/?s=Naruto")
        AnimesOnlineCloud.search_anime("Naruto")
        self.get.assert_called_once()

    def test_search_stops_pagination_cycles(self):
        first = BASE + "/?s=Naruto"
        second = BASE + "/page/2/?s=Naruto"
        self.get.side_effect = [response(result("Naruto", ANIME) + pagination(second), url=first),
                                response(result("Outro", "/anime/outro") + pagination(first), url=second)]
        AnimesOnlineCloud.search_anime("Naruto")
        self.assertEqual(self.get.call_count, 2)

    def test_search_has_twenty_page_cap(self):
        self.assertEqual(cloud.MAX_SEARCH_PAGES, 20)
        self.get.side_effect = [response(result(str(n), f"/anime/{n}") + pagination(f"/page/{n + 1}/?s=x"),
                                         url=BASE + ("/?s=x" if n == 1 else f"/page/{n}/?s=x"))
                                for n in range(1, 21)]
        AnimesOnlineCloud.search_anime("x")
        self.assertEqual(self.get.call_count, 20)
        self.assertEqual(len(self.rep.get_anime_titles()), 20)

    def test_search_rejects_foreign_result_and_next_hosts(self):
        for bad in ("https://evil.example/", "http://animesonline.cloud/", "https://animesonline.cloud.evil/",
                    "https://user@animesonline.cloud/", "//evil.example/", "javascript:alert(1)"):
            with self.subTest(url=bad):
                self.get.reset_mock()
                self.get.return_value = response(result("Bad", bad) + result("Naruto", ANIME)
                                                  + pagination(bad), url=BASE + "/?s=x")
                AnimesOnlineCloud.search_anime("x")
                self.get.assert_called_once()
                self.assertEqual(self.rep.get_anime_titles(), ["Naruto [AnimesOnlineCloud]"])

    def test_search_network_error_does_not_publish_partial_results(self):
        self.get.side_effect = [response(result("Naruto", ANIME) + pagination("/page/2/?s=x"),
                                         url=BASE + "/?s=x"), requests.Timeout("timeout")]
        with self.assertRaisesRegex(RuntimeError, "falha ao consultar"):
            AnimesOnlineCloud.search_anime("x")
        self.assertEqual(self.rep.get_anime_titles(), [])

    def test_modern_episode_order_is_numeric_and_titles_remain_aligned(self):
        numbers = ["10", "2.5", "2.05", "2", "1.00000000000000000002", "1.00000000000000000001"]
        html = seasons(season(1, "".join(card(n, "Title " + n, "id-" + n) for n in numbers)))
        titles, urls = self.episode_list(html)
        ordered = [numbers[i] for i in (5, 4, 3, 2, 1, 0)]
        self.assertEqual(titles, [f"T1 EP. {n} - Title {n}" for n in ordered])
        self.assertEqual(urls, [BASE + "/episodio/id-" + n for n in ordered])

    def test_modern_ascending_219_episodes_are_not_reversed(self):
        titles, urls = self.episode_list(seasons(season(1, "".join(
            card(n, f"Title {n}", f"naruto-{n}") for n in range(1, 220)))))
        self.assertEqual(len(titles), 219)
        self.assertEqual(titles[0], "T1 EP. 1 - Title 1")
        self.assertEqual(titles[-1], "T1 EP. 219 - Title 219")
        self.assertEqual(urls, [BASE + f"/episodio/naruto-{n}" for n in range(1, 220)])

    def test_seasons_sort_by_se_t_not_dom_or_lexical_order(self):
        html = seasons(season("10", card(1, "Ten", "s10e1"))
                       + season("Temporada 2", card(2, "Two B", "s2e2") + card(1, "Two A", "s2e1"))
                       + season("1ª Temporada", card(10, "One B", "s1e10") + card(1, "One A", "s1e1")))
        titles, urls = self.episode_list(html)
        self.assertEqual(titles, ["T1 EP. 1 - One A", "T1 EP. 10 - One B", "T2 EP. 1 - Two A",
                                  "T2 EP. 2 - Two B", "T10 EP. 1 - Ten"])
        self.assertEqual(urls, [BASE + "/episodio/" + slug for slug in ("s1e1", "s1e10", "s2e1", "s2e2", "s10e1")])

    def test_modern_invalid_numbers_cards_duplicates_and_title_fallbacks(self):
        html = seasons(season(1,
            "".join(card(n, "Invalid", "bad-" + str(i))
                    for i, n in enumerate(("NaN", "sNaN", "Infinity", "-Infinity", "-1", "", "bad")))
            + '<div class="episode-card" data-episode-number="1" data-episode-title="Missing anchor"></div>'
            + card(2, "  Data   title  ", "two") + card(99, "Duplicate", "two")
            + card("1.5", "", "special", visible="Visible fallback")
            + card(1, "", "one", visible="")))
        titles, urls = self.episode_list(html)
        self.assertEqual(titles, ["T1 EP. 1", "T1 EP. 1.5 - Visible fallback", "T1 EP. 2 - Data title"])
        self.assertEqual(urls, [BASE + "/episodio/" + slug for slug in ("one", "special", "two")])

    def test_episode_bad_href_does_not_shift_titles_or_consume_valid_entry(self):
        html = seasons(season(1,
            '<div class="episode-card" data-episode-number="1" data-episode-title="Bad">'
            '<a href="https://evil.example/episodio/one">Link</a></div>'
            + card(2, "Good", "good")))
        self.assertEqual(self.episode_list(html), (["T1 EP. 2 - Good"], [BASE + "/episodio/good"]))

    def test_legacy_season_episode_labels_and_deduplication(self):
        html = '<ul class="episodios">' + (
            legacy("10 - 1", "Ten", "ten") + legacy("2 - 10", "Two ten", "two-ten")
            + legacy("2x2.5", "Special", "special") + legacy("1 - 10", "One ten", "one-ten")
            + legacy("1 - 2", "One two", "one-two") + legacy("9 - 99", "Duplicate", "one-two")) + '</ul>'
        titles, urls = self.episode_list(html)
        self.assertEqual(titles, ["T1 EP. 2 - One two", "T1 EP. 10 - One ten", "T2 EP. 2.5 - Special",
                                  "T2 EP. 10 - Two ten", "T10 EP. 1 - Ten"])
        self.assertEqual(urls, [BASE + "/episodio/" + slug for slug in
                                ("one-two", "one-ten", "special", "two-ten", "ten")])

    def test_legacy_scalar_numbers_use_season_marker_and_unknown_order_is_stable(self):
        html = seasons(season(2, '<ul class="episodios">' + legacy("10", "Ten", "ten")
                               + legacy("2.5", "Special", "special") + legacy("", "Unnumbered", "unknown")
                               + legacy("", "Another", "another") + '</ul>'))
        titles, urls = self.episode_list(html)
        self.assertEqual(titles, ["T2 EP. 2.5 - Special", "T2 EP. 10 - Ten", "T2 Unnumbered", "T2 Another"])
        self.assertEqual(urls[-2:], [BASE + "/episodio/unknown", BASE + "/episodio/another"])

    def test_legacy_fallback_when_no_valid_modern_cards(self):
        html = seasons(season(1, card("NaN", "Invalid", "invalid")))
        html += '<ul class="episodios">' + legacy("1", "Legacy", "legacy") + '</ul>'
        self.assertEqual(self.episode_list(html), (["EP. 1 - Legacy"], [BASE + "/episodio/legacy"]))

    def test_empty_episodes_raise_without_publishing(self):
        self.get.return_value = response("", url=ANIME)
        with self.assertRaisesRegex(RuntimeError, "nenhum episódio válido"):
            AnimesOnlineCloud.search_episodes("Naruto", ANIME, None)
        self.assertEqual(dict(self.rep.anime_episodes_urls), {})

    def test_direct_video_src_takes_priority_over_legacy(self):
        self.get.return_value = response(f'<video src="{MEDIA}"></video>' + PLAYER)
        AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
        self.assertEqual(self.container, [MEDIA])
        self.assertTrue(self.event.is_set())
        self.get.assert_called_once()
        self.blogger.assert_not_called()

    def test_live_jujutsu_video_source_shape(self):
        episode = BASE + "/episodio/jujutsu-kaisen-shimetsu-kaiyuu-zenpen-dublado-episodio-01"
        self.get.return_value = response(f'<video controls><source src="{MEDIA}" type="video/mp4"></video>', url=episode)
        AnimesOnlineCloud.search_player_src(episode, self.container, self.event)
        self.assertEqual(self.container, [MEDIA])
        self.assertTrue(self.event.is_set())

    def servers(self, *sources):
        """Página no layout atual: um .animeq-player__source por servidor."""
        return "".join(f'<div class="animeq-player__source">{source}</div>' for source in sources)

    def test_dead_mp4_server_falls_through_to_blogger_iframe(self):
        # Jujutsu Kaisen 1: o mp4 do mangas.cloud responde 404, o Blogger funciona.
        dead = "https://mangas.cloud/Animes/Letra-J/Jujutsu%20Kaisen/01.mp4"
        self.get.return_value = response(self.servers(
            f'<video><source src="{dead}"></video>', f'<iframe src="{BLOGGER}"></iframe>'))
        self.alive.side_effect = lambda stream, headers: stream != dead
        AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
        self.assertEqual(self.container, [GOOGLEVIDEO])
        self.assertTrue(self.event.is_set())

    def test_servers_are_tried_in_site_order(self):
        self.get.return_value = response(self.servers(
            f'<iframe src="{BLOGGER}"></iframe>', f'<video><source src="{MEDIA}"></video>'))
        AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
        self.assertEqual(self.container, [GOOGLEVIDEO])
        self.alive.assert_called_once_with(
            GOOGLEVIDEO, {"User-Agent": cloud.utils.BLOGGER_USER_AGENT})

    def test_unverifiable_server_is_kept_as_fallback(self):
        self.get.return_value = response(self.servers(f'<video><source src="{MEDIA}"></video>'))
        self.alive.return_value = None
        AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
        self.assertEqual(self.container, [MEDIA])

    def test_verified_server_beats_unverifiable_earlier_one(self):
        slow = "https://slow.example/a.mp4"
        self.get.return_value = response(self.servers(
            f'<video><source src="{slow}"></video>', f'<video><source src="{MEDIA}"></video>'))
        self.alive.side_effect = lambda stream, headers: None if stream == slow else True
        AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
        self.assertEqual(self.container, [MEDIA])

    def test_all_servers_dead_raises_without_publishing(self):
        self.get.return_value = response(self.servers(f'<video><source src="{MEDIA}"></video>'))
        self.alive.return_value = False
        with self.assertRaisesRegex(RuntimeError, "nenhum player suportado"):
            AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
        self.assertEqual(self.container, [])
        self.assertFalse(self.event.is_set())

    def test_direct_sources_skip_invalid_values_and_resolve_relative_urls(self):
        for src, expected in (("//media.example/video.mp4", "https://media.example/video.mp4"),
                              ("/media/play?id=1", BASE + "/media/play?id=1"),
                              ("http://media.example/video.mp4", "http://media.example/video.mp4")):
            with self.subTest(src=src):
                self.event.clear()
                self.container.clear()
                self.get.return_value = response('<video src="javascript:alert(1)"><source src="data:video/mp4;base64,AA">'
                                                  f'<source src="{escape(src, quote=True)}"></video>')
                AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
                self.assertEqual(self.container, [expected])

    def test_legacy_endpoint_attribute_alignment_and_real_json_decoding(self):
        api = response(url=ENDPOINT)
        api.json.side_effect = lambda: json.loads(r'{"other":"ignore","embed_url":"https:\/\/media.example\/file.mp4?token=a%2Bb&sig=x=y"}')
        page = response(PLAYER)
        self.get.side_effect = [page, api]
        AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
        self.assertEqual(self.container, ["https://media.example/file.mp4?token=a%2Bb&sig=x=y"])
        self.assertEqual(self.get.call_args_list, [
            call(url, headers=cloud.HEADERS, timeout=(5, 20), allow_redirects=False)
            for url in (EPISODE, ENDPOINT)])
        for item in (page, api):
            item.raise_for_status.assert_called_once_with()
            item.__exit__.assert_called_once()

    def test_direct_legacy_embeds_and_iframe_fragment(self):
        for embed, expected in ((MEDIA, MEDIA), ("https://media.example/master.m3u8?token=a%2Bb", "https://media.example/master.m3u8?token=a%2Bb"),
                                ('<iframe src="//media.example/video.mp4?x=1&amp;y=2"></iframe>',
                                 "https://media.example/video.mp4?x=1&y=2")):
            with self.subTest(embed=embed):
                self.event.clear()
                self.container.clear()
                self.resolve(payload={"embed_url": embed})
                self.assertEqual(self.container, [expected])

    def test_jwplayer_source_decodes_query_once_without_requesting_wrapper(self):
        source = "https://media.example/master.m3u8?token=a%2Bb&sig=x=y"
        embed = "https://player.example/jwplayer?" + urlencode({"source": source})
        self.resolve(payload={"embed_url": embed})
        self.assertEqual(self.container, [source])
        self.assertEqual(self.get.call_count, 2)

    def test_unsupported_embed_pages_and_unsafe_media_are_not_published(self):
        unsafe = ("https://player.example/embed/123", BLOGGER.replace("www.blogger.com", "www.blogger.com.evil"),
                  "javascript:alert(1)", "file:///tmp/video.mp4", "data:video/mp4;base64,AA", "https:///missing.mp4",
                  "https://user:secret@media.example/file.mp4", "https://media.example:bad/video.mp4", "#player",
                  '<script>location="https://media.example/video.mp4"</script>')
        for embed in unsafe:
            with self.subTest(embed=embed):
                self.resolve_failure(embed)
        self.blogger.assert_not_called()

    def resolve_failure(self, embed):
        with self.assertRaisesRegex(RuntimeError, "nenhum player suportado"):
            self.resolve(payload={"embed_url": embed})
        self.assert_not_published()
        self.assertTrue(all(args.args[0].startswith(BASE + "/") for args in self.get.call_args_list))

    def test_jwplayer_rejects_unsafe_missing_or_ambiguous_source(self):
        for query in ("", "source=javascript%3Aalert%281%29", "source=file%3A%2F%2F%2Ftmp%2Fvideo",
                      "source=%2Frelative.mp4", "source=https%3A%2F%2Fu%40media.example%2Fv.mp4",
                      "source=https%3A%2F%2Fa.example%2Fa.mp4&source=https%3A%2F%2Fb.example%2Fb.mp4"):
            with self.subTest(query=query):
                self.resolve_failure("https://player.example/jwplayer?" + query)

    def test_blogger_fallback_uses_existing_resolver(self):
        self.resolve(payload={"embed_url": BLOGGER})
        self.blogger.assert_called_once_with(BLOGGER)
        self.assertEqual(self.container, [GOOGLEVIDEO])
        self.assertTrue(self.event.is_set())

    def test_blogger_unresolved_or_invalid_return_is_not_published(self):
        for value in (BLOGGER, "javascript:alert(1)", "file:///tmp/video", None):
            with self.subTest(value=value):
                self.blogger.return_value = value
                self.resolve_failure(BLOGGER)

    def test_failed_blogger_option_can_fall_back_to_next_player(self):
        self.blogger.side_effect = RuntimeError("Video is unavailable")
        second = OPTION.replace('data-nume="1"', 'data-nume="2"')
        self.get.side_effect = [response('<ul id="playeroptionsul">' + OPTION + second + '</ul>'),
                                response(url=ENDPOINT, payload={"embed_url": BLOGGER}),
                                response(url=ENDPOINT[:-1] + "2", payload={"embed_url": MEDIA})]
        AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
        self.assertEqual(self.container, [MEDIA])
        self.assertEqual(self.get.call_args_list[-1].args[0], ENDPOINT[:-1] + "2")

    def test_invalid_legacy_attributes_and_duplicate_endpoints_are_skipped(self):
        malformed = OPTION.replace('data-post="42"', 'data-post="../evil"')
        html = '<ul id="playeroptionsul">' + malformed + '<li data-post="42"></li>' + OPTION * 2 + '</ul>'
        with self.assertRaisesRegex(RuntimeError, "nenhum player suportado"):
            self.resolve(html=html, payload={"embed_url": "https://unsupported.example/embed"})
        self.assertEqual(self.get.call_args_list[-1].args[0], ENDPOINT)
        self.assertEqual(self.get.call_count, 2)
        self.assert_not_published()

    def test_invalid_json_shapes_and_missing_embed_url(self):
        for payload in (None, [], "not an object", {}, {"embed_url": None}, {"embed_url": 42}):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(RuntimeError, "JSON sem embed_url"):
                    self.resolve(payload=payload)
                self.assert_not_published()

    def test_malformed_json_is_reported_and_response_closed(self):
        api = response(url=ENDPOINT)
        api.json.side_effect = ValueError("invalid JSON")
        self.get.side_effect = [response(PLAYER), api]
        with self.assertRaisesRegex(RuntimeError, "JSON inválido"):
            AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
        self.assert_not_published()
        api.__exit__.assert_called_once()

    def test_no_player_is_an_error_without_publication(self):
        self.get.return_value = response('<iframe src="https://unsupported.example/embed"></iframe>')
        with self.assertRaisesRegex(RuntimeError, "nenhum player suportado"):
            AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
        self.assert_not_published()

    def test_cancellation_before_request(self):
        self.event.set()
        AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
        self.get.assert_not_called()
        self.assertEqual(self.container, [])

    def test_cancellation_after_provider_request(self):
        def get(*args, **kwargs):
            self.event.set()
            return response(f'<video src="{MEDIA}"></video>' + PLAYER)
        self.get.side_effect = get
        AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
        self.get.assert_called_once()
        self.assertEqual(self.container, [])

    def test_cancellation_before_legacy_request(self):
        page = response(PLAYER)
        page.__exit__.side_effect = lambda *args: self.event.set() or False
        self.get.return_value = page
        AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
        self.get.assert_called_once()
        self.assertEqual(self.container, [])

    def test_cancellation_after_legacy_request_and_during_json_parsing(self):
        for during_json in (False, True):
            with self.subTest(during_json=during_json):
                self.event.clear()
                api = response(url=ENDPOINT, payload={"embed_url": BLOGGER})
                if during_json:
                    def payload():
                        self.event.set()
                        return {"embed_url": BLOGGER}
                    api.json.side_effect = payload
                def get(url, during_json=during_json, api=api, **kwargs):
                    if url == EPISODE:
                        return response(PLAYER)
                    if not during_json:
                        self.event.set()
                    return api
                self.get.side_effect = get
                AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
                self.assertEqual(self.container, [])
                self.blogger.assert_not_called()

    def test_cancellation_after_blogger_resolution(self):
        def blogger(url):
            self.event.set()
            return GOOGLEVIDEO
        self.blogger.side_effect = blogger
        self.resolve(payload={"embed_url": BLOGGER})
        self.assertEqual(self.container, [])

    def test_network_errors_do_not_publish_or_set_event(self):
        for failure in (requests.Timeout("timeout"), requests.ConnectionError("offline")):
            with self.subTest(failure=failure):
                self.get.side_effect = failure
                with self.assertRaisesRegex(RuntimeError, "falha ao consultar"):
                    AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
                self.assert_not_published()
        self.get.side_effect = [response(PLAYER), requests.Timeout("endpoint timeout")]
        with self.assertRaisesRegex(RuntimeError, "endpoint timeout"):
            AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
        self.assert_not_published()

    def test_http_errors_are_checked_and_responses_closed(self):
        for status in (403, 404, 500, 304):
            with self.subTest(status=status):
                item = response(f'<video src="{MEDIA}"></video>', status=status)
                self.get.return_value = item
                with self.assertRaises(RuntimeError):
                    AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
                item.raise_for_status.assert_called_once_with()
                item.__exit__.assert_called_once()
                self.assert_not_published()

    def test_provider_rejects_unsafe_urls_before_any_network(self):
        urls = ("https://evil.example/anime", "http://animesonline.cloud/anime", "https://animesonline.cloud.evil/anime",
                "https://animesonline.cloud@evil.example/anime", "https://user@animesonline.cloud/anime",
                "https://user:pass@animesonline.cloud/anime", "https://animesonline.cloud:444/anime",
                "https://animesonline.cloud:bad/anime", "file:///tmp/page", "javascript:alert(1)",
                "https://[invalid/", "https:///missing", "https://animesonline.cloud\\@evil.example/anime",
                "https://animesonline.cloud/\nevil")
        for url in urls:
            with self.subTest(url=url):
                with self.assertRaises(RuntimeError):
                    AnimesOnlineCloud.search_player_src(url, self.container, self.event)
                with self.assertRaises(RuntimeError):
                    AnimesOnlineCloud.search_episodes("Anime", url, None)
                self.get.assert_not_called()
                self.assert_not_published()

    def test_redirects_reject_unsafe_target_without_requesting_it(self):
        for location in ("https://evil.example/page", "//evil.example/page", "http://animesonline.cloud/page",
                         "https://user@animesonline.cloud/page", "https://animesonline.cloud.evil/page",
                         "javascript:alert(1)", "https://animesonline.cloud:444/page", None):
            with self.subTest(location=location):
                self.get.reset_mock()
                item = response(status=302, headers={"Location": location} if location else {})
                self.get.return_value = item
                with self.assertRaisesRegex(RuntimeError, "redirecionamento não permitido"):
                    AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
                self.get.assert_called_once()
                item.__exit__.assert_called_once()
                self.assert_not_published()

    def test_same_host_redirects_follow_relative_location_with_protocol_guards(self):
        target = BASE + "/episodio/new"
        self.get.side_effect = [response(status=302, headers={"Location": "/episodio/new"}),
                                response(f'<video src="{MEDIA}"></video>', url=target)]
        AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
        self.assertEqual(self.container, [MEDIA])
        self.assertEqual(self.get.call_args_list, [
            call(url, headers=cloud.HEADERS, timeout=(5, 20), allow_redirects=False)
            for url in (EPISODE, target)])

    def test_redirect_cycles_and_limit(self):
        self.get.return_value = response(status=302, headers={"Location": EPISODE})
        with self.assertRaisesRegex(RuntimeError, "ciclo"):
            AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
        self.get.assert_called_once()
        self.get.reset_mock()
        self.get.side_effect = [response(url=EPISODE if n == 0 else BASE + f"/redirect/{n}", status=307,
                                         headers={"Location": f"/redirect/{n + 1}"})
                                for n in range(cloud.MAX_REDIRECTS + 1)]
        with self.assertRaisesRegex(RuntimeError, "limite de redirecionamentos"):
            AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
        self.assertEqual(self.get.call_count, cloud.MAX_REDIRECTS + 1)
        self.assert_not_published()

    def test_cancellation_after_redirect_response_does_not_follow(self):
        item = response(status=302, headers={"Location": "/episodio/new"})
        item.__exit__.side_effect = lambda *args: self.event.set() or False
        self.get.return_value = item
        AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
        self.get.assert_called_once()
        self.assertEqual(self.container, [])

    def test_unexpected_foreign_response_url_is_rejected(self):
        self.get.return_value = response(f'<video src="{MEDIA}"></video>', url="https://evil.example/page")
        with self.assertRaisesRegex(RuntimeError, "resposta fora do provedor"):
            AnimesOnlineCloud.search_player_src(EPISODE, self.container, self.event)
        self.assert_not_published()


if __name__ == "__main__":
    unittest.main()
