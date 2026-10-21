# SPDX-License-Identifier: Apache-2.0
# Copyright 2015 Javier Tomás (conforme README do projeto upstream).
# Contribuições: yuzono e colaboradores de yuzono/anime-extensions.
# Adaptação MODIFICADA de AnimeFire.kt para o CLI ani-guarani: requests,
# episódios em ordem crescente, identidade por ID e publicação do HLS sem proxy.
# Upstream: https://github.com/yuzono/anime-extensions/blob/
# ee94f0850f42f3becefeab01a0bc53033e8b52ff/
# src/pt/animefire/src/eu/kanade/tachiyomi/animeextension/pt/animefire/AnimeFire.kt
# Licença: Apache-2.0; consulte LICENSES/Apache-2.0.txt e os notices fornecidos.

import math
import re
from typing import ClassVar
from urllib.parse import parse_qs, urlencode, urlsplit

import requests

from loader import PluginInterface
from repository import rep

BASE_URL = "https://animefire.one"
API_URL = "https://api.animefire.one"
HEADERS = {
    "Referer": BASE_URL + "/",
    "Origin": BASE_URL,
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
}
REQUEST_TIMEOUT = (5, 20)
MAX_SEARCH_PAGES = 100


def _require(condition, field):
    if not condition:
        raise RuntimeError(f"AnimeFire: resposta da API inválida ({field}).")


def _id(value):
    _require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]+", value), "ID")
    return value


def _title(anime):
    _require(isinstance(anime, dict), "anime")
    anime_id = _id(anime.get("id"))
    titles = anime.get("titles")
    _require(isinstance(titles, dict) and all(isinstance(v, str) for v in titles.values()), "titles")
    title = next((titles[key].strip() for key in ("BR", "US", "JP")
                  if titles.get(key, "").strip()), None)
    title = title or next((value.strip() for value in titles.values() if value.strip()), anime_id)
    # O Repository mescla títulos iguais, mesmo de fontes ou IDs diferentes.
    return anime_id, f"{title} [AnimeFire: {anime_id}]"


def _request(path, **params):
    url = API_URL + path
    try:
        with requests.get(url, headers=HEADERS, params={"v": 3, **params},
                          timeout=REQUEST_TIMEOUT) as response:
            response.raise_for_status()
            payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"AnimeFire: JSON inválido em {url}.") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"AnimeFire: falha ao consultar {url}: {exc}") from exc
    _require(isinstance(payload, dict) and "data" in payload, "data")
    return payload


def _anime_url(url, episode=False):
    message = (
        "AnimeFire: link antigo ou inválido. Faça uma nova busca e selecione o anime "
        "e o episódio no novo site animefire.one; URLs antigas não podem ser reutilizadas."
    )
    try:
        parts = urlsplit(url)
        match = re.fullmatch(r"/anime/([A-Za-z0-9_-]+)/?", parts.path)
        if (parts.scheme not in ("http", "https") or parts.netloc != "animefire.one"
                or not match or parts.fragment):
            raise ValueError("URL não suportada")
        anime_id = _id(match[1])
        if not episode:
            return anime_id
        query = parse_qs(parts.query, keep_blank_values=True)
        ids = query.get("episode", [])
        if len(ids) != 1:
            raise ValueError("Falta ID único do episódio")
        return anime_id, _id(ids[0])
    except (TypeError, ValueError, RuntimeError) as exc:
        raise RuntimeError(message) from exc


def _number(value, field, integer=False):
    _require(type(value) in ((int,) if integer else (int, float)), field)
    _require(value >= 0 and (isinstance(value, int) or math.isfinite(value)), field)
    return value


def _stream_url(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        parts = urlsplit(value)
        if parts.scheme in ("http", "https") and parts.netloc and parts.hostname:
            return value
    except ValueError:
        pass
    return None


class AnimeFire(PluginInterface):
    languages: ClassVar[list[str]] = ["pt-br"]
    name = "animefire"
    priority = 90

    @staticmethod
    def search_anime(query):
        seen = set()
        results = []
        for page in range(1, MAX_SEARCH_PAGES + 1):
            payload = _request("/animes/pesquisar", q=query.strip(), page=page)
            data, meta = payload["data"], payload.get("meta")
            if not isinstance(data, list) or not isinstance(meta, dict):
                raise RuntimeError("AnimeFire: resposta da API inválida (pesquisa/meta).")
            current, last = meta.get("current_page"), meta.get("last_page")
            _require(type(current) is int and type(last) is int
                     and current == page and last >= current, "paginação sem progresso")
            entries = [_title(anime) for anime in data]
            new_entries = [(anime_id, title) for anime_id, title in entries if anime_id not in seen]
            _require(not data or new_entries, "paginação repetida sem progresso")
            for anime_id, title in new_entries:
                if anime_id not in seen:
                    seen.add(anime_id)
                    results.append((anime_id, title))
            if current == last:
                break
            _require(bool(new_entries), "paginação vazia sem progresso")
        else:
            raise RuntimeError("AnimeFire: paginação excedeu o limite de segurança.")
        for anime_id, title in results:
            rep.add_anime(title, f"{BASE_URL}/anime/{anime_id}", AnimeFire.name)

    @staticmethod
    def search_episodes(anime, url, params):
        anime_id = _anime_url(url)
        data = _request(f"/anime/{anime_id}")["data"]
        _require(isinstance(data, dict), "detalhes")
        hero_id, _ = _title(data.get("hero"))
        _require(hero_id == anime_id, "hero.id não corresponde ao anime")
        seasons, episodes = data.get("seasons"), data.get("episodes")
        _require(isinstance(seasons, list) and isinstance(episodes, list), "seasons/episodes")
        for season in seasons:
            _require(isinstance(season, dict), "season")
            _number(season.get("number"), "season.number", integer=True)
            _number(season.get("first_episode_number"), "first_episode_number", integer=True)
        entries = []
        for episode in episodes:
            _require(isinstance(episode, dict), "episode")
            episode_id = _id(episode.get("id"))
            number = _number(episode.get("number"), "episode.number")
            season = episode.get("season")
            if season is not None:
                _number(season, "episode.season", integer=True)
            title = episode.get("title")
            _require(title is None or isinstance(title, str), "episode.title")
            label = (f"T{season} " if season is not None else "") + f"EP. {number:g}"
            if title and title.strip():
                label += " - " + title.strip()
            episode_url = f"{BASE_URL}/anime/{anime_id}?{urlencode({'episode': episode_id})}"
            entries.append((season or 0, number, label, episode_url))
        entries.sort(key=lambda entry: entry[:2])
        if not entries:
            raise RuntimeError("AnimeFire: nenhum episódio disponível para este anime.")
        rep.add_episode_list(anime, [entry[2] for entry in entries],
                             [entry[3] for entry in entries], AnimeFire.name)

    @staticmethod
    def search_player_src(url_episode, container, event):
        if event.is_set():
            return
        anime_id, episode_id = _anime_url(url_episode, episode=True)
        data = _request(f"/episode/{episode_id}")["data"]
        if event.is_set():
            return
        _require(isinstance(data, dict), "playback")
        parent_id, _ = _title(data.get("anime"))
        _require(parent_id == anime_id, "playback.anime.id não corresponde ao anime")
        streams = data.get("streams")
        _require(isinstance(streams, list), "streams")
        candidates = []
        for stream in streams:
            _require(isinstance(stream, dict), "stream")
            offline, mtl = stream.get("is_offline", False), stream.get("is_mtl", False)
            _require(type(offline) is bool and type(mtl) is bool, "is_offline/is_mtl")
            if offline or stream.get("url") is None:
                continue
            audio = stream.get("audio")
            _require(audio in ("legendado", "dublado"), "stream.audio")
            url = _stream_url(stream.get("url"))
            if url:
                candidates.append((mtl, audio != "legendado", url))
        if not candidates:
            raise RuntimeError("AnimeFire: nenhum stream HTTP(S) disponível; episódios/streams offline.")
        # Prioriza tradução original; entre streams não MTL, prefere legendado.
        url = min(candidates, key=lambda candidate: candidate[:2])[2]
        if not event.is_set():
            container.append(url)
            event.set()


def load(languages_dict):
    if any(language in languages_dict for language in AnimeFire.languages):
        rep.register(AnimeFire)
