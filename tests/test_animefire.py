import copy
import subprocess
import sys
import unittest
from threading import Event
from unittest.mock import MagicMock, Mock, call, patch

import requests

from plugins import animefire
from plugins.animefire import AnimeFire
from repository import Repository

BASE = "https://animefire.one"
API = "https://api.animefire.one"
MASTER = "https://akumast.net/i/original/master.m3u8?token=a%2Bb&sig=x=y"
ANIME = {"id": "anime-1", "titles": {"BR": "Nome brasileiro", "US": "English", "JP": "日本語"}}


def response(payload):
    result = MagicMock()
    result.__enter__.return_value = result
    result.json.return_value = payload
    return result


def search_page(data, current=1, last=1):
    return {"data": data, "meta": {"current_page": current, "last_page": last}}


def details(episodes=None):
    return {"data": {
        "hero": ANIME,
        "seasons": [
            {"number": 2, "first_episode_number": 13, "title": "Segunda"},
            {"number": 1, "first_episode_number": 1, "title": "Primeira"},
        ],
        "episodes": episodes if episodes is not None else [
            {"id": "ep-22", "season": 2, "number": 2, "title": "Final"},
            {"id": "ep-12", "season": 1, "number": 2, "title": "Dois"},
            {"id": "ep-21", "season": 2, "number": 1, "title": "Retorno"},
            {"id": "ep-11", "season": 1, "number": 1, "title": "Início"},
        ],
    }}


def stream(url: object = MASTER, audio="legendado", **flags):
    return {"audio": audio, "url": url, **flags}


def playback(streams):
    return {"data": {"anime": ANIME, "streams": streams}}


class AnimeFireTests(unittest.TestCase):
    def setUp(self):
        self.rep = Repository()
        self.repo_patch = patch.object(animefire, "rep", self.rep)
        self.repo_patch.start()
        self.addCleanup(self.repo_patch.stop)
        self.get = self.enterContext(patch("plugins.animefire.requests.get"))
        self.event = Event()
        self.container = []
        self.episode_url = BASE + "/anime/anime-1?episode=ep-1"

    def resolve(self, payload):
        self.get.return_value = response(payload)
        AnimeFire.search_player_src(self.episode_url, self.container, self.event)

    def assert_not_published(self):
        self.assertEqual(self.container, [])
        self.assertFalse(self.event.is_set())

    def test_paginated_search_preserves_titles_ids_and_request_protocol(self):
        other = {"id": "anime-2", "titles": {"BR": "Outro", "US": "Other"}}
        first, second = response(search_page([ANIME], 1, 2)), response(search_page([other], 2, 2))
        self.get.side_effect = [first, second]
        query = "  ação & aventura / 日本語?  "
        AnimeFire.search_anime(query)
        self.assertEqual(self.rep.anime_to_urls, {
            "Nome brasileiro [AnimeFire: anime-1]": [(BASE + "/anime/anime-1", "animefire", None)],
            "Outro [AnimeFire: anime-2]": [(BASE + "/anime/anime-2", "animefire", None)],
        })
        self.assertEqual(self.get.call_args_list, [
            call(API + "/animes/pesquisar", headers=animefire.HEADERS,
                 params={"v": 3, "q": query.strip(), "page": page}, timeout=(5, 20))
            for page in (1, 2)
        ])
        self.assertEqual(animefire.HEADERS, {
            "Referer": BASE + "/", "Origin": BASE,
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
        })
        for item in (first, second):
            item.raise_for_status.assert_called_once_with()
            item.__exit__.assert_called_once()

    def test_title_fallbacks_and_same_titles_do_not_merge_sources_or_ids(self):
        self.rep.add_anime("Mesmo nome", "https://other.example/anime", "other")
        entries = [
            {"id": "a", "titles": {"BR": "Mesmo nome"}},
            {"id": "b", "titles": {"BR": "Mesmo nome"}},
            {"id": "c", "titles": {"BR": "  ", "US": "English", "JP": "Japonês"}},
            {"id": "d", "titles": {"JP": "Japonês"}},
            {"id": "e", "titles": {"FR": "Autre"}},
            {"id": "f", "titles": {}},
        ]
        self.get.return_value = response(search_page(entries))
        AnimeFire.search_anime("nome")
        self.assertEqual(len(self.rep.anime_to_urls), 7)
        for entry, title in zip(entries, ("Mesmo nome", "Mesmo nome", "English", "Japonês", "Autre", "f")):
            anime_id = entry["id"]
            self.assertEqual(self.rep.anime_to_urls[f"{title} [AnimeFire: {anime_id}]"],
                             [(BASE + "/anime/" + anime_id, "animefire", None)])

    def test_search_deduplicates_ids_across_overlapping_pages(self):
        other = {"id": "b", "titles": {"BR": "B"}}
        self.get.side_effect = [response(search_page([ANIME, ANIME], 1, 2)),
                                response(search_page([ANIME, other], 2, 2))]
        AnimeFire.search_anime("nome")
        self.assertEqual(len(self.rep.anime_to_urls), 2)
        self.assertTrue(all(len(entries) == 1 for entries in self.rep.anime_to_urls.values()))

    def test_empty_search(self):
        self.get.return_value = response(search_page([]))
        AnimeFire.search_anime("inexistente")
        self.assertEqual(self.rep.get_anime_titles(), [])

    def test_repeated_page_metadata_does_not_loop_or_publish_partial_results(self):
        self.get.return_value = response(search_page([ANIME], 1, 2))
        with self.assertRaisesRegex(RuntimeError, "paginação"):
            AnimeFire.search_anime("nome")
        self.assertEqual(self.get.call_count, 2)
        self.assertEqual(self.rep.get_anime_titles(), [])

    def test_repeated_data_with_advancing_metadata_does_not_loop(self):
        self.get.side_effect = [response(search_page([ANIME], 1, 999)),
                                response(search_page([ANIME], 2, 999))]
        with self.assertRaisesRegex(RuntimeError, "sem progresso"):
            AnimeFire.search_anime("nome")
        self.assertEqual(self.get.call_count, 2)

    def test_empty_intermediate_page_is_not_followed_indefinitely(self):
        self.get.return_value = response(search_page([], 1, 999))
        with self.assertRaisesRegex(RuntimeError, "sem progresso"):
            AnimeFire.search_anime("nome")
        self.get.assert_called_once()

    def test_pagination_has_hard_limit_even_if_last_page_keeps_moving(self):
        self.get.side_effect = [
            response(search_page([{"id": str(page), "titles": {}}], page, page + 1))
            for page in (1, 2)
        ]
        with patch.object(animefire, "MAX_SEARCH_PAGES", 2), \
                self.assertRaisesRegex(RuntimeError, "limite de segurança"):
            AnimeFire.search_anime("nome")
        self.assertEqual(self.get.call_count, 2)

    def test_invalid_search_schemas_and_path_ids(self):
        invalid = [None, [], {}, {"data": {}}, {"data": [], "meta": None},
                   search_page([], True, 1), search_page([], 1, 0),
                   search_page([{"id": "../evil", "titles": {}}]),
                   search_page([{"id": "a/b", "titles": {}}]),
                   search_page([{"id": 12, "titles": {}}]),
                   search_page([{"id": "a", "titles": []}]),
                   search_page([{"id": "a", "titles": {"BR": None}}])]
        for payload in invalid:
            with self.subTest(payload=payload):
                self.get.return_value = response(payload)
                with self.assertRaisesRegex(RuntimeError, "API inválida"):
                    AnimeFire.search_anime("nome")
                self.assertEqual(self.rep.get_anime_titles(), [])

    def test_all_seasons_have_one_chronological_episode_list(self):
        self.get.return_value = response(details())
        AnimeFire.search_episodes("Escolhido", BASE + "/anime/anime-1", None)
        self.assertEqual(self.rep.get_episode_list("Escolhido"), [
            "T1 EP. 1 - Início", "T1 EP. 2 - Dois", "T2 EP. 1 - Retorno", "T2 EP. 2 - Final",
        ])
        self.assertEqual(self.rep.anime_episodes_urls["Escolhido"], [([
            BASE + "/anime/anime-1?episode=" + episode_id
            for episode_id in ("ep-11", "ep-12", "ep-21", "ep-22")
        ], "animefire")])
        self.get.assert_called_once_with(API + "/anime/anime-1", headers=animefire.HEADERS,
                                         params={"v": 3}, timeout=(5, 20))

    def test_fractional_episode_numbers_and_missing_season_title(self):
        self.get.return_value = response(details([
            {"id": "special", "number": 1.5, "season": None, "title": "  "},
            {"id": "first", "number": 1},
        ]))
        AnimeFire.search_episodes("A", BASE + "/anime/anime-1", {})
        self.assertEqual(self.rep.get_episode_list("A"), ["EP. 1", "EP. 1.5"])

    def test_bad_episode_schema_does_not_publish_partial_list(self):
        bad = []
        for field, value in (("id", "a/b"), ("number", "2"), ("number", float("nan")),
                             ("number", True), ("season", -1), ("title", [])):
            payload = copy.deepcopy(details())
            payload["data"]["episodes"][0][field] = value
            bad.append(payload)
        for payload in bad + [{"data": {}}, details([])]:
            with self.subTest(payload=payload):
                self.get.return_value = response(payload)
                with self.assertRaises(RuntimeError):
                    AnimeFire.search_episodes("A", BASE + "/anime/anime-1", None)
                self.assertEqual(self.rep.get_episode_list("A"), [])

    def test_details_parent_id_must_match_requested_id(self):
        self.get.return_value = response(details())
        with self.assertRaisesRegex(RuntimeError, "não corresponde"):
            AnimeFire.search_episodes("A", BASE + "/anime/another", None)

    def test_legacy_and_invalid_urls_require_new_search_without_network(self):
        urls = [
            "https://animefire.plus/animes/nome-todos-os-episodios",
            "https://animefire.io/animes/nome/1",
            BASE + "/animes/nome/1", BASE + "/anime/anime-1/1",
            BASE + "/anime/../evil?episode=ep-1",
            BASE + "/anime/a%2Fb?episode=ep-1",
            "https://evil.example/anime/anime-1?episode=ep-1",
            "https://animefire.one.evil.example/anime/anime-1?episode=ep-1",
            "https://user@animefire.one/anime/anime-1?episode=ep-1",
            "https://[broken", None,
        ]
        for url in urls:
            for method in (lambda url=url: AnimeFire.search_episodes("A", url, None),
                           lambda url=url: AnimeFire.search_player_src(url, self.container, self.event)):
                with self.subTest(url=url), self.assertRaisesRegex(RuntimeError, "nova busca"):
                    method()
        self.get.assert_not_called()
        self.assert_not_published()

    def test_episode_query_id_must_be_unique_nonempty_and_not_path(self):
        for suffix in ("", "?episode=", "?episode=../x", "?episode=a%2Fb",
                       "?episode=a&episode=b", "?episode=%3Fother%3Dx"):
            with self.subTest(suffix=suffix), self.assertRaisesRegex(RuntimeError, "nova busca"):
                AnimeFire.search_player_src(BASE + "/anime/anime-1" + suffix, self.container, self.event)
        self.get.assert_not_called()

    def test_original_legendado_wins_without_fetching_playlist(self):
        self.resolve(playback([
            stream("https://akumast.net/i/mtl", is_mtl=True),
            stream("https://akumast.net/i/dub", audio="dublado"),
            stream("https://akumast.net/i/offline", is_offline=True),
            stream(None), stream("  " + MASTER + "  "),
        ]))
        self.assertEqual(self.container, [MASTER])
        self.assertTrue(self.event.is_set())
        self.get.assert_called_once_with(API + "/episode/ep-1", headers=animefire.HEADERS,
                                         params={"v": 3}, timeout=(5, 20))

    def test_non_mtl_dub_wins_over_automatic_subtitles(self):
        dubbed = "https://akumast.net/i/dublado"
        self.resolve(playback([stream(is_mtl=True), stream(dubbed, audio="dublado")]))
        self.assertEqual(self.container, [dubbed])

    def test_mtl_is_usable_as_last_resort(self):
        self.resolve(playback([stream(is_mtl=True)]))
        self.assertEqual(self.container, [MASTER])
        self.assertTrue(self.event.is_set())

    def test_invalid_stream_urls_are_skipped_before_valid_http_url(self):
        valid = "http://cdn.example/master.m3u8"
        self.resolve(playback([stream(value) for value in (
            "javascript:alert(1)", "file:///tmp/video", "blob:https://x/id", "https:",
            "//akumast.net/i/id", "https://[broken", 42, "", valid,
        )]))
        self.assertEqual(self.container, [valid])
        self.assertTrue(self.event.is_set())

    def test_offline_null_empty_or_invalid_streams_do_not_publish(self):
        for streams in ([], [stream(is_offline=True)], [stream(None)], [stream("")],
                        [stream("javascript:alert(1)")]):
            with self.subTest(streams=streams), self.assertRaisesRegex(RuntimeError, "nenhum stream"):
                self.resolve(playback(streams))
            self.assert_not_published()

    def test_invalid_playback_schemas_do_not_publish(self):
        payloads = [{"data": None}, {"data": {}}, playback(None), playback([None]),
                    playback([stream(is_offline="false")]), playback([stream(is_mtl=1)]),
                    playback([stream(audio="unknown")])]
        mismatch = playback([stream()])
        mismatch["data"]["anime"] = {"id": "another", "titles": {}}
        for payload in payloads + [mismatch]:
            with self.subTest(payload=payload), self.assertRaisesRegex(RuntimeError, "API inválida"):
                self.resolve(payload)
            self.assert_not_published()

    def test_network_and_status_failures_preserve_cause_and_do_not_publish(self):
        for error in (requests.ConnectTimeout("connect"), requests.ReadTimeout("read"),
                      requests.ConnectionError("offline"), requests.HTTPError("503 unavailable")):
            with self.subTest(error=error):
                result = response(playback([stream()]))
                result.raise_for_status.side_effect = error
                self.get.return_value = result
                with self.assertRaisesRegex(RuntimeError, "AnimeFire.*falha") as caught:
                    AnimeFire.search_player_src(self.episode_url, self.container, self.event)
                self.assertIs(caught.exception.__cause__, error)
                result.__exit__.assert_called_once()
                result.json.assert_not_called()
                self.assert_not_published()

    def test_connection_failure_before_response(self):
        error = requests.ConnectTimeout("timeout")
        self.get.side_effect = error
        with self.assertRaises(RuntimeError) as caught:
            AnimeFire.search_anime("nome")
        self.assertIs(caught.exception.__cause__, error)

    def test_invalid_json_closes_response_and_preserves_cause(self):
        for error in (ValueError("bad JSON"), requests.exceptions.JSONDecodeError("bad JSON", "x", 0)):
            with self.subTest(error=error):
                result = response(None)
                result.json.side_effect = error
                self.get.return_value = result
                with self.assertRaisesRegex(RuntimeError, "JSON inválido") as caught:
                    AnimeFire.search_player_src(self.episode_url, self.container, self.event)
                self.assertIs(caught.exception.__cause__, error)
                result.__exit__.assert_called_once()
                self.assert_not_published()

    def test_cancelled_before_request_does_not_access_network(self):
        self.event.set()
        AnimeFire.search_player_src(self.episode_url, self.container, self.event)
        self.get.assert_not_called()
        self.assertEqual(self.container, [])

    def test_cancellation_during_request_does_not_publish(self):
        result = response(None)

        def cancel():
            self.event.set()
            return playback([stream()])

        result.json.side_effect = cancel
        self.get.return_value = result
        AnimeFire.search_player_src(self.episode_url, self.container, self.event)
        self.assertEqual(self.container, [])
        result.__exit__.assert_called_once()

    def test_cancellation_immediately_before_publish_does_not_set_event(self):
        event = Mock()
        event.is_set.side_effect = [False, False, True]
        self.get.return_value = response(playback([stream()]))
        AnimeFire.search_player_src(self.episode_url, self.container, event)
        self.assertEqual(self.container, [])
        event.set.assert_not_called()

    def test_load_preserves_language_registration(self):
        animefire.load({"en": True})
        self.assertEqual(self.rep.sources, {})
        animefire.load({"pt-br": True})
        self.assertIs(self.rep.sources["animefire"], AnimeFire)

    def test_import_does_not_require_selenium_beautifulsoup_or_utils(self):
        code = (
            "import sys; "
            "sys.modules['selenium'] = None; sys.modules['bs4'] = None; "
            "sys.modules['plugins.utils'] = None; "
            "from plugins.animefire import AnimeFire; "
            "assert AnimeFire.name == 'animefire'"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                timeout=10, check=False, cwd=animefire.__file__.rsplit("/plugins/", 1)[0])
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
