"""Agregação de fontes com falhas isoladas e escrita sincronizada."""
import logging
from collections import defaultdict
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

    def get_anime_titles(self):
        return sorted(self.anime_to_urls, key=str.casefold)

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

    def search_player(self, anime, episode_num):
        if episode_num < 1:
            raise ValueError("Número de episódio deve ser positivo.")
        candidates = [(urls[episode_num - 1], source)
                      for urls, source in self.anime_episodes_urls[anime]
                      if source in self.sources and len(urls) >= episode_num]
        if not candidates:
            raise RuntimeError("Nenhuma fonte disponível para este episódio. Faça uma nova busca.")
        event = Event()

        def resolve(url, source):
            container = []
            self.sources[source].search_player_src(url, container, event)
            return container[0] if container else None

        # O contexto aguarda o cleanup dos navegadores, mesmo depois do primeiro resultado.
        result = None
        with ThreadPoolExecutor(max_workers=min(4, len(candidates))) as pool:
            pending = {pool.submit(resolve, url, source): source for url, source in candidates}
            for future in as_completed(pending):
                try:
                    url = future.result()
                    if url is not None:
                        if not isinstance(url, str):
                            raise ValueError("URL de player inválida.")
                        url = url.strip()
                        parsed = urlsplit(url)
                        if parsed.scheme not in ("http", "https") or not parsed.netloc:
                            raise ValueError("URL de player inválida.")
                        if result is None:
                            result = url
                            event.set()
                except Exception as exc:
                    log.warning("Player da fonte %s: %s", pending[future], exc)
        if not result:
            raise RuntimeError("Nenhum player encontrado. O site pode ter mudado ou estar indisponível.")
        return result


rep = Repository()
