"""Agregação de fontes com falhas isoladas e escrita sincronizada."""
import logging
from collections import defaultdict
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event, RLock
from urllib.parse import urlsplit

from loader import PluginInterface

log = logging.getLogger(__name__)


class Repository:
    def __init__(self):
        self.sources = {}
        self.anime_to_urls = defaultdict(list)
        self.anime_episodes_titles = defaultdict(list)
        self.anime_episodes_urls = defaultdict(list)
        self._lock = RLock()
        self.query = ""

    def register(self, plugin: PluginInterface):
        self.sources[plugin.name] = plugin

    def _run(self, jobs):
        if not jobs:
            return
        with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as pool:
            pending = {pool.submit(fn, *args): source for source, fn, args in jobs}
            for future in as_completed(pending):
                try:
                    future.result()
                except Exception as exc:
                    log.warning("Fonte %s: %s", pending[future], exc, exc_info=log.isEnabledFor(logging.DEBUG))

    def search_anime(self, query):
        self.anime_to_urls.clear()
        self.anime_episodes_titles.clear()
        self.anime_episodes_urls.clear()
        if not self.sources:
            raise RuntimeError("Nenhuma fonte disponível. Verifique as dependências e --source.")
        self.query = query
        self._run([(name, plugin.search_anime, (query,)) for name, plugin in self.sources.items()])

    def add_anime(self, title, url, source, params=None):
        # Não mesclar títulos aproximados: temporadas e dublagens podem diferir.
        title = " ".join(title.split())
        if not title:
            return
        with self._lock:
            key = next((key for key in self.anime_to_urls if key.casefold() == title.casefold()), title)
            entry = (url, source, params)
            if entry not in self.anime_to_urls[key]:
                self.anime_to_urls[key].append(entry)

    @staticmethod
    def _words(text):
        text = unicodedata.normalize("NFKD", text).casefold()
        return "".join(c if c.isalnum() else " " for c in text if not unicodedata.combining(c)).split()

    def get_anime_titles(self):
        titles = sorted(self.anime_to_urls, key=str.casefold)
        wanted = self._words(self.query)
        # Algumas APIs devolvem resultados aproximados; mostra só os que contêm a busca.
        relevant = [t for t in titles if wanted and set(wanted) <= set(self._words(t))]
        return relevant or titles

    def search_episodes(self, anime):
        if self.anime_episodes_titles.get(anime):
            return
        self._run([(source, self.sources[source].search_episodes, (anime, url, params))
                   for url, source, params in self.anime_to_urls[anime] if source in self.sources])

    def add_episode_list(self, anime, title_list, url_list, source):
        if not title_list or len(title_list) != len(url_list):
            raise ValueError("Lista de episódios vazia ou inconsistente.")
        with self._lock:
            self.anime_episodes_titles[anime].append(list(title_list))
            self.anime_episodes_urls[anime].append((list(url_list), source))

    def get_episode_list(self, anime):
        return max(self.anime_episodes_titles.get(anime, []), key=len, default=[])

    def search_players(self, anime, episode_num):
        """Gera URLs de player, da fonte mais confiável para a menos confiável."""
        if episode_num < 1:
            raise ValueError("Número de episódio deve ser positivo.")
        candidates = [(urls[episode_num - 1], source)
                      for urls, source in self.anime_episodes_urls[anime]
                      if source in self.sources and len(urls) >= episode_num]
        if not candidates:
            raise RuntimeError("Nenhuma fonte disponível para este episódio. Faça uma nova busca.")
        candidates.sort(key=lambda item: getattr(self.sources[item[1]], "priority", 50))
        found = False
        for url, source in candidates:
            container = []
            try:
                self.sources[source].search_player_src(url, container, Event())
                result = container[0].strip() if container and isinstance(container[0], str) else None
                parsed = urlsplit(result) if result else None
                if not parsed or parsed.scheme not in ("http", "https") or not parsed.netloc:
                    raise ValueError("URL de player inválida.")
            except Exception as exc:
                log.warning("Player da fonte %s: %s", source, exc)
                continue
            found = True
            yield result
        if not found:
            raise RuntimeError("Nenhum player encontrado. O site pode ter mudado ou estar indisponível.")

    def search_player(self, anime, episode_num):
        return next(self.search_players(anime, episode_num))


rep = Repository()
