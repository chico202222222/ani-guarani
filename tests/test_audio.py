"""Opção legendado/dublado: classificação, filtro, escolha no CLI e AnimeFire."""
import unittest
from threading import Event
from unittest.mock import MagicMock, patch

import main
from plugins import animefire
from plugins.animefire import AnimeFire
from repository import Repository, audio_from_title

MASTER = "https://akumast.net/i/original/master.m3u8"


class ClassificationTests(unittest.TestCase):
    def test_titles_are_subbed_unless_marked_dubbed(self):
        cases = {
            "Jujutsu Kaisen": {"legendado"},
            "Jujutsu Kaisen Dublado": {"dublado"},
            "Jujutsu Kaisen (Dublado)": {"dublado"},
            "Naruto Clássico (Legendado)": {"legendado"},
            "Boruto Dub": {"dublado"},
            "Dublado & Legendado": {"dublado", "legendado"},
            "Dubai Story": {"legendado"},
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(audio_from_title(title), expected)


class RepositoryAudioTests(unittest.TestCase):
    def setUp(self):
        self.rep = Repository()
        self.rep.query = "jujutsu"
        self.rep.add_anime("Jujutsu Kaisen", "u1", "a")
        self.rep.add_anime("Jujutsu Kaisen Dublado", "u2", "a")
        self.rep.add_anime("Jujutsu Kaisen [Fire]", "u3", "b", audio=["dublado", "legendado"])

    def test_filter_by_audio(self):
        self.assertEqual(self.rep.get_anime_titles("dublado"),
                         ["Jujutsu Kaisen [Fire]", "Jujutsu Kaisen Dublado"])
        self.assertEqual(self.rep.get_anime_titles("legendado"),
                         ["Jujutsu Kaisen", "Jujutsu Kaisen [Fire]"])
        self.assertEqual(len(self.rep.get_anime_titles()), 3)

    def test_available_audios_follow_fixed_order(self):
        self.assertEqual(self.rep.available_audios(), ["legendado", "dublado"])
        only_dub = Repository()
        only_dub.add_anime("Naruto Dublado", "u", "a")
        self.assertEqual(only_dub.available_audios(), ["dublado"])
        self.assertEqual(Repository().available_audios(), [])

    def test_explicit_audio_wins_over_title_and_merges_same_title(self):
        self.rep.add_anime("Jujutsu Kaisen", "u4", "c", audio=["dublado"])
        self.assertEqual(self.rep.anime_audio["Jujutsu Kaisen"], {"legendado", "dublado"})

    def test_new_search_clears_audio(self):
        self.rep.sources["x"] = MagicMock()
        self.rep.search_anime("outro")
        self.assertFalse(self.rep.anime_audio)


class ChooseAudioTests(unittest.TestCase):
    def setUp(self):
        self.rep = Repository()
        self.enterContext(patch.object(main, "rep", self.rep))
        self.menu = self.enterContext(patch.object(main, "menu"))

    def both(self):
        self.rep.add_anime("Naruto", "u1", "a")
        self.rep.add_anime("Naruto Dublado", "u2", "a")

    def test_flag_skips_menu(self):
        self.both()
        self.assertEqual(main.choose_audio("dublado"), "dublado")
        self.assertIsNone(main.choose_audio("todos"))
        self.menu.assert_not_called()

    def test_flag_without_results_fails_clearly(self):
        self.rep.add_anime("Naruto", "u1", "a")
        with self.assertRaisesRegex(RuntimeError, "Nenhum resultado dublado"):
            main.choose_audio("dublado")

    def test_menu_only_when_both_exist(self):
        self.rep.add_anime("Naruto", "u1", "a")
        self.assertIsNone(main.choose_audio(None))
        self.menu.assert_not_called()
        self.both()
        for label, expected in (("Legendado", "legendado"), ("Dublado", "dublado"), ("Todos", None)):
            self.menu.return_value = label
            self.assertEqual(main.choose_audio(None), expected)

    def test_cli_accepts_audio_and_new_sources(self):
        with patch.object(main, "main") as run:
            self.assertEqual(main.cli(["-q", "x", "--audio", "dublado", "--source", "anitube",
                                       "--source", "animesdigital"]), 0)
        args = run.call_args.args[0]
        self.assertEqual((args.audio, args.source), ("dublado", ["anitube", "animesdigital"]))
        with self.assertRaises(SystemExit):
            main.cli(["--audio", "falado"])


class AnimeFireAudioTests(unittest.TestCase):
    ANIME = {"id": "anime-1", "titles": {"BR": "Nome"}}

    def setUp(self):
        self.rep = Repository()
        self.enterContext(patch.object(animefire, "rep", self.rep))
        self.get = self.enterContext(patch("plugins.animefire.requests.get"))

    def reply(self, payload):
        result = MagicMock()
        result.__enter__.return_value = result
        result.json.return_value = payload
        self.get.return_value = result

    def test_search_uses_api_audio_field(self):
        cases = {"Dublado & Legendado": {"dublado", "legendado"}, "Dublado": {"dublado"},
                 "Legendado": {"legendado"}}
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.rep.anime_audio.clear()
                self.reply({"data": [{**self.ANIME, "audio": text}], "meta": {"current_page": 1, "last_page": 1}})
                AnimeFire.search_anime("nome")
                self.assertEqual(self.rep.anime_audio["Nome [AnimeFire: anime-1]"], expected)

    def test_missing_audio_field_falls_back_to_title(self):
        self.reply({"data": [self.ANIME], "meta": {"current_page": 1, "last_page": 1}})
        AnimeFire.search_anime("nome")
        self.assertEqual(self.rep.anime_audio["Nome [AnimeFire: anime-1]"], {"legendado"})

    def play(self, wanted):
        self.rep.audio = wanted
        self.reply({"data": {"anime": self.ANIME, "streams": [
            {"audio": "legendado", "url": MASTER + "?s"}, {"audio": "dublado", "url": MASTER + "?d"}]}})
        container = []
        AnimeFire.search_player_src(animefire.BASE_URL + "/anime/anime-1?episode=e1", container, Event())
        return container

    def test_stream_follows_chosen_audio(self):
        self.assertEqual(self.play("dublado"), [MASTER + "?d"])
        self.assertEqual(self.play("legendado"), [MASTER + "?s"])
        self.assertEqual(self.play(None), [MASTER + "?s"])

    def test_missing_chosen_audio_is_an_error_not_a_silent_swap(self):
        self.rep.audio = "dublado"
        self.reply({"data": {"anime": self.ANIME, "streams": [{"audio": "legendado", "url": MASTER}]}})
        with self.assertRaisesRegex(RuntimeError, "não tem stream dublado"):
            AnimeFire.search_player_src(animefire.BASE_URL + "/anime/anime-1?episode=e1", [], Event())


if __name__ == "__main__":
    unittest.main()
