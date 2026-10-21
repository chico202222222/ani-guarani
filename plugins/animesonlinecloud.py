# SPDX-License-Identifier: Apache-2.0
# Atribuição: yuzono e colaboradores de yuzono/anime-extensions.
# MODIFICADO: adaptação de AnimesOnlineCloud.kt para Python e API do ani-guarani,
# seletores HTML atuais, ordenação numérica e validação de URLs/redirecionamentos.
# Upstream: https://github.com/yuzono/anime-extensions/blob/
# ee94f0850f42f3becefeab01a0bc53033e8b52ff/
# src/pt/animesonlinecloud/src/eu/kanade/tachiyomi/animeextension/pt/animesonlinecloud/AnimesOnlineCloud.kt
# Licença: Apache-2.0; consulte LICENSES/Apache-2.0.txt.

import re
from decimal import Decimal, InvalidOperation
from typing import ClassVar
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from loader import PluginInterface
from plugins import utils
from repository import rep

BASE_URL = "https://animesonline.cloud"
HEADERS = {"Referer": BASE_URL + "/"}
REQUEST_TIMEOUT = (5, 20)
MAX_SEARCH_PAGES = 20
MAX_REDIRECTS = 5


def _cancelled(event):
    return event is not None and event.is_set()


def _http_url(value, base=None):
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if (value.startswith("#") or "\\" in value
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)):
        return None
    try:
        original = urlsplit(value)
        if original.scheme and (original.scheme not in ("http", "https") or not original.hostname):
            return None
        value = urljoin(base, value) if base else value
        parts = urlsplit(value)
        if (parts.scheme not in ("http", "https") or not parts.hostname
                or parts.username is not None or parts.password is not None):
            return None
        # Accessing port also validates malformed/non-numeric ports.
        if parts.port == 0:
            return None
        return parts._replace(fragment="").geturl()
    except ValueError:
        return None


def _provider_url(value, base=BASE_URL + "/"):
    value = _http_url(value, base)
    if value:
        parts = urlsplit(value)
        if (parts.scheme == "https" and parts.hostname == "animesonline.cloud"
                and parts.port in (None, 443)):
            return parts._replace(netloc="animesonline.cloud").geturl()
    return None


def _request(url, event=None, json=False):
    seen = set()
    for _ in range(MAX_REDIRECTS + 1):
        if _cancelled(event):
            return None
        url = _provider_url(url)
        if not url:
            raise RuntimeError("AnimesOnlineCloud: URL fora do provedor HTTPS permitido.")
        if url in seen:
            raise RuntimeError("AnimesOnlineCloud: redirecionamento em ciclo.")
        seen.add(url)
        try:
            with requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT,
                              allow_redirects=False) as response:
                if _cancelled(event):
                    return None
                response.raise_for_status()
                final_url = _provider_url(response.url)
                if not final_url:
                    raise RuntimeError("AnimesOnlineCloud: resposta fora do provedor permitido.")
                if response.status_code in (301, 302, 303, 307, 308):
                    # Validate Location before making another request, not after following it.
                    url = _provider_url(response.headers.get("Location"), final_url)
                    if not url:
                        raise RuntimeError("AnimesOnlineCloud: redirecionamento não permitido.")
                    continue
                if not 200 <= response.status_code < 300:
                    raise RuntimeError("AnimesOnlineCloud: status HTTP inesperado.")
                payload = response.json() if json else response.text
                if _cancelled(event):
                    return None
                return payload, final_url
        except requests.RequestException as exc:
            raise RuntimeError(f"AnimesOnlineCloud: falha ao consultar {url}: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError(f"AnimesOnlineCloud: JSON inválido em {url}.") from exc
    raise RuntimeError("AnimesOnlineCloud: limite de redirecionamentos excedido.")


def _decimal(value):
    try:
        number = Decimal(value.strip())
        return number if number.is_finite() and number >= 0 else None
    except (AttributeError, InvalidOperation, ValueError):
        return None


def _season(node):
    parent = node.find_parent(class_="se-c")
    marker = parent.select_one(".se-q .se-t") if parent else None
    match = re.search(r"\d+(?:\.\d+)?", marker.get_text(" ", strip=True)) if marker else None
    return _decimal(match[0]) if match else None


def _text(value):
    return " ".join(value.split())


def _episode_label(season, number, title):
    prefix = f"T{season:g} " if season is not None else ""
    if number is None:
        return prefix + (title or "Episódio")
    label = prefix + f"EP. {number:g}"
    return label + (" - " + title if title else "")


def _episodes(soup, page_url):
    entries, seen = [], set()

    def add(node, season, number, title):
        url = _provider_url(node.get("href"), page_url) if node else None
        if url and url not in seen:
            seen.add(url)
            entries.append((season if season is not None else Decimal(0),
                            number is None, number if number is not None else Decimal(0),
                            _episode_label(season, number, title), url))

    for card in soup.select("#seasons .episode-card"):
        number = _decimal(card.get("data-episode-number", ""))
        if number is None:
            continue
        title = _text(card.get("data-episode-title", ""))
        marker = card.select_one(".episode-title")
        if not title and marker:
            title = marker.get_text(" ", strip=True)
        add(card.select_one("a[href]"), _season(card), number, title)

    if not entries:
        for anchor in soup.select("ul.episodios .episodiotitle a[href]"):
            row = anchor.find_parent("li")
            marker = row.select_one(".numerando") if row else None
            label = marker.get_text(" ", strip=True) if marker else ""
            season, number = _season(anchor), _decimal(label)
            pair = re.fullmatch(r"(\d+(?:\.\d+)?)\s*[-xX×]\s*(\d+(?:\.\d+)?)", label)
            if pair:
                season, number = _decimal(pair[1]), _decimal(pair[2])
            add(anchor, season, number, anchor.get_text(" ", strip=True))

    # Especiais sem temporada vão para o fim, depois da numeração regular.
    entries.sort(key=lambda entry: (entry[0] == 0 and entry[3].startswith("EP."), *entry[:3]))
    return [entry[3] for entry in entries], [entry[4] for entry in entries]


def _is_blogger(url):
    parts = urlsplit(url)
    return parts.hostname in {"blogger.com", "www.blogger.com"} and parts.path == "/video.g"


def _resolve_embed(value, page_url, event):
    if not isinstance(value, str) or _cancelled(event):
        return None
    # Some DooPlay installations put an iframe fragment in embed_url.
    if value.lstrip().startswith("<"):
        frame = BeautifulSoup(value, "html.parser").select_one("iframe[src]")
        value = frame.get("src") if frame else None
    url = _http_url(value, page_url)
    if not url:
        return None
    parts = urlsplit(url)
    if _is_blogger(url):
        resolved = utils.resolve_blogger_player(url)
        if _cancelled(event):
            return None
        resolved = _http_url(resolved)
        # The existing helper can return the unchanged, unresolved Blogger page.
        return resolved if resolved and not _is_blogger(resolved) else None
    if parts.path.rstrip("/").rsplit("/", 1)[-1] == "jwplayer":
        sources = parse_qs(parts.query).get("source", [])
        return _http_url(sources[0]) if len(sources) == 1 else None
    if parts.path.lower().endswith((".mp4", ".m3u8")):
        return url
    return None


class AnimesOnlineCloud(PluginInterface):
    languages: ClassVar[list[str]] = ["pt-br"]
    name = "animesonlinecloud"
    priority = 0

    @staticmethod
    def search_anime(query):
        if not query.strip():
            return
        results = AnimesOnlineCloud._search(query.strip())
        # O site devolve página vazia para algumas buscas com maiúsculas
        # ("Jujutsu Kaisen"), mas acha tudo em minúsculas.
        if not results and query.strip() != query.strip().casefold():
            results = AnimesOnlineCloud._search(query.strip().casefold())
        for title, url in results:
            rep.add_anime(title, url, AnimesOnlineCloud.name, params=None)

    @staticmethod
    def _search(query):
        url = BASE_URL + "/?" + urlencode({"s": query})
        pages, seen, results = set(), set(), []
        for _ in range(MAX_SEARCH_PAGES):
            if not url or url in pages:
                break
            pages.add(url)
            response = _request(url)
            if response is None:
                return []
            html, page_url = response
            pages.add(page_url)
            soup = BeautifulSoup(html, "html.parser")
            previous = len(results)
            for anchor in soup.select(".result-item .title a[href]"):
                title = anchor.get_text(" ", strip=True)
                link = _provider_url(anchor.get("href"), page_url)
                if title and link and link not in seen:
                    seen.add(link)
                    results.append((title + " [AnimesOnlineCloud]", link))
            if len(results) == previous:
                break
            url = next((link for anchor in soup.select(
                'div.pagination a[rel~="next"][href], div.pagination a.next[href]')
                if (link := _provider_url(anchor.get("href"), page_url))), None)
        return results

    @staticmethod
    def search_episodes(anime, url, params):
        response = _request(url)
        if response is None:
            return
        html, page_url = response
        titles, urls = _episodes(BeautifulSoup(html, "html.parser"), page_url)
        if not urls and BeautifulSoup(html, "html.parser").select_one("ul#playeroptionsul li"):
            # Filmes/OVAs têm o player na própria página.
            titles, urls = ["Filme"], [page_url]
        if not urls:
            raise RuntimeError("AnimesOnlineCloud: nenhum episódio válido encontrado.")
        rep.add_episode_list(anime, titles, urls, AnimesOnlineCloud.name)

    @staticmethod
    def search_player_src(url, container, event):
        response = _request(url, event)
        if response is None:
            return
        html, page_url = response
        soup = BeautifulSoup(html, "html.parser")

        def publish(stream):
            if stream and not event.is_set():
                container.append(stream)
                event.set()
                return True
            return False

        for node in soup.select("video[src], video source[src]"):
            if publish(_http_url(node.get("src"), page_url)):
                return
        error, seen = None, set()
        for option in soup.select("ul#playeroptionsul li"):
            if event.is_set():
                return
            parts = [option.get(key, "") for key in ("data-post", "data-type", "data-nume")]
            if not all(re.fullmatch(r"[A-Za-z0-9_-]+", part) for part in parts):
                continue
            endpoint = BASE_URL + "/wp-json/dooplayer/v2/" + "/".join(parts)
            if endpoint in seen:
                continue
            seen.add(endpoint)
            try:
                response = _request(endpoint, event, json=True)
                if response is None:
                    return
                payload, _ = response
                if not isinstance(payload, dict) or not isinstance(payload.get("embed_url"), str):
                    error = RuntimeError("AnimesOnlineCloud: JSON sem embed_url válido.")
                    continue
                stream = _resolve_embed(payload["embed_url"], page_url, event)
                if publish(stream):
                    return
            except RuntimeError as exc:
                error = exc
        if not event.is_set():
            raise RuntimeError("AnimesOnlineCloud: nenhum player suportado com mídia HTTP(S)."
                               + (f" {error}" if error else "")) from error


def load(languages_dict):
    if any(language in languages_dict for language in AnimesOnlineCloud.languages):
        # O repositório recebe classes, apesar da anotação de register indicar instâncias.
        rep.register(AnimesOnlineCloud)  # pyright: ignore[reportArgumentType]
