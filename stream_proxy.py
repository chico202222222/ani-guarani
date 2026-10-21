"""Relay HLS local e restrito para os streams AnimeFire hospedados no Akumast."""

import re
import secrets
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import requests

REQUEST_TIMEOUT = (5, 20)
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_ROUTES = 10000
_CDN = "akumast.net"
_URI = re.compile(r'(?<![\w-])URI="([^"]*)"')
_RANGE = re.compile(r"bytes=(?:[0-9]+-[0-9]*|-[0-9]+)\Z")
_PLAYLIST_TAGS = {"#EXT-X-MEDIA", "#EXT-X-I-FRAME-STREAM-INF", "#EXT-X-RENDITION-REPORT"}


class _RelayError(RuntimeError):
    def __init__(self, message, status=502):
        super().__init__(f"AnimeFire: {message}")
        self.status = status


class _ManifestRedirect(Exception):
    def __init__(self, location):
        self.location = location


def _validate_url(url):
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.hostname != _CDN
                or parts.netloc.lower() not in {_CDN, _CDN + ":443"}
                or parts.port not in (None, 443) or parts.username is not None
                or parts.password is not None or parts.fragment
                or not parts.path.startswith("/i/")
                or any(ord(char) <= 32 or ord(char) == 127 for char in url)
                or "\\" in url):
            raise ValueError
        # Impede que escapes/dot-segments sejam normalizados para fora de /i/.
        path = parts.path
        for _ in range(8):
            decoded = unquote(path)
            if decoded == path:
                break
            path = decoded
        if ("%" in path or "\\" in path or not path.startswith("/i/")
                or any(part in {".", ".."} for part in path.split("/"))
                or any(ord(char) <= 32 or ord(char) == 127 for char in path)):
            raise ValueError
        return urlunsplit(("https", _CDN, parts.path, parts.query, ""))
    except (TypeError, ValueError) as exc:
        raise _RelayError("URL recusada; esperado HTTPS akumast.net:443 com caminho /i/.") from exc


def _is_manifest(body):
    return body.startswith((b"#EXTM3U", b"\xef\xbb\xbf#EXTM3U"))


def _fetch(url, byte_range=None, context="recurso HLS"):
    url = _validate_url(url)
    headers = {"Accept-Encoding": "identity", "Referer": "https://animefire.one/",
               "Origin": "https://animefire.one"}
    if byte_range:
        headers["Range"] = byte_range
    try:
        with requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT,
                          verify=True, allow_redirects=False, stream=True) as response:
            status = response.status_code
            if status not in (200, 206):
                detail = " (stream indisponível)" if status == 404 else ""
                if 300 <= status < 400:
                    detail = " (redirecionamento recusado)"
                raise _RelayError(f"{context}: HTTP {status}{detail}.",
                                  status if 400 <= status < 600 else 502)
            body = bytearray()
            limit = MAX_RESPONSE_BYTES
            for chunk in response.iter_content(chunk_size=64 * 1024):
                body.extend(chunk)
                if _is_manifest(body):
                    limit = min(limit, MAX_MANIFEST_BYTES)
                if len(body) > limit:
                    raise _RelayError(f"{context}: resposta excedeu o limite de segurança.")
            return bytes(body), status, response.headers.get("Content-Range")
    except requests.RequestException as exc:
        # Não inclui URLs assinadas, tokens ou o texto potencialmente sensível da exceção.
        raise _RelayError(f"{context}: falha de rede ({type(exc).__name__}).") from exc


def _kind(url):
    name = urlsplit(url).path.rsplit("/", 1)[-1].lower()
    stem = name.rsplit(".", 1)[0]
    if name.endswith(".m3u8") or stem in {"h", "master", "index", "playlist"} or re.fullmatch(
            r"(?:quality[-_]?)?\d{3,4}p?", stem):
        return "manifest"
    return "media"


class _Relay:
    def __init__(self):
        self.token = secrets.token_urlsafe(24)
        self.routes = {}
        self.ids = {}
        self.lock = threading.Lock()
        self.initial: tuple[str, bytes] | None = None
        self.base = ""

    def register(self, url, kind=None):
        url = _validate_url(url)
        kind = kind or _kind(url)
        key = (url, kind)
        with self.lock:
            path = self.ids.get(key)
            if path is None:
                if len(self.routes) >= MAX_ROUTES:
                    raise _RelayError("limite de rotas HLS atingido.")
                suffix = ".m3u8" if kind == "manifest" else ".mp4"
                path = f"/{self.token}/{secrets.token_urlsafe(16)}{suffix}"
                self.ids[key] = path
                self.routes[path] = key
        return self.base + path

    def rewrite(self, body, source):
        try:
            text = body.decode("utf-8-sig")
        except UnicodeError as exc:
            raise _RelayError("manifesto HLS não é UTF-8 válido.") from exc
        output = []
        variant = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                kind = "manifest" if variant else None
                output.append(self.register(urljoin(source, stripped), kind))
                variant = False
            elif stripped.startswith("#"):
                tag = stripped.split(":", 1)[0]
                kind = "manifest" if tag in _PLAYLIST_TAGS else None
                if tag in {"#EXT-X-KEY", "#EXT-X-SESSION-KEY"}:
                    kind = "key"

                def replace(match, kind=kind):
                    target = urljoin(source, match[1])
                    return 'URI="' + self.register(target, kind) + '"'

                output.append(_URI.sub(replace, line))
                if tag == "#EXT-X-STREAM-INF":
                    variant = True
            else:
                output.append(line)
        return ("\n".join(output) + "\n").encode("utf-8")

    def resource(self, path, byte_range, head=False):
        with self.lock:
            entry = self.routes.get(path)
            initial = self.initial if self.initial and self.initial[0] == path and not byte_range else None
            if initial and not head:
                self.initial = None
        if entry is None:
            raise _RelayError("rota inexistente.", 404)
        url, kind = entry
        if initial:
            body, status, content_range = initial[1], 200, None
        else:
            body, status, content_range = _fetch(url, byte_range)
        if _is_manifest(body):
            # Um Range de sondagem do player não deve truncar um manifesto reescrito.
            if status == 206:
                body, status, content_range = _fetch(url, context="manifesto HLS completo")
                if status != 200 or not _is_manifest(body):
                    raise _RelayError("manifesto HLS completo inválido.")
            if kind != "manifest":
                # A extensão é apenas uma pista; bytes HLS exigem uma rota .m3u8.
                raise _ManifestRedirect(self.register(url, "manifest"))
            return self.rewrite(body, url), 200, "application/vnd.apple.mpegurl", None
        if kind == "manifest":
            raise _RelayError("resposta não contém um manifesto #EXTM3U.")
        mime = "application/octet-stream" if kind == "key" else "video/mp4"
        return body, status, mime, content_range


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    relay: _Relay


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # O caminho contém o token de acesso; nem sucessos nem erros são registrados.
        pass

    def do_HEAD(self):
        self._serve(head=True)

    def do_GET(self):
        self._serve(head=False)

    def _serve(self, head):
        self.connection.settimeout(REQUEST_TIMEOUT[1])
        relay = cast(_Server, self.server).relay
        location = None
        try:
            if self.headers.get("Host") != relay.base.removeprefix("http://"):
                raise _RelayError("Host local inválido.", 403)
            ranges = self.headers.get_all("Range", [])
            byte_range = ranges[0] if ranges else None
            if len(ranges) > 1 or (byte_range is not None and not _RANGE.fullmatch(byte_range)):
                raise _RelayError("Range inválido; use um único intervalo em bytes.", 400)
            body, status, mime, content_range = relay.resource(self.path, byte_range, head)
        except _ManifestRedirect as exc:
            location = exc.location
            body, status, mime, content_range = b"", 307, "application/vnd.apple.mpegurl", None
        except _RelayError as exc:
            body, status, mime, content_range = str(exc).encode("utf-8"), exc.status, "text/plain; charset=utf-8", None
        try:
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if location:
                self.send_header("Location", location)
            if status == 206 and content_range:
                self.send_header("Content-Range", content_range)
                self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            if not head:
                self.wfile.write(body)
        except (ConnectionError, OSError):
            pass


@contextmanager
def animefire_stream(url):
    """Yield uma URL para mpv; manter o contexto aberto durante toda a reprodução.

    Outros hosts passam inalterados, sem rede/servidor. URLs Akumast inválidas,
    falhas de preflight e manifestos inseguros geram RuntimeError antes do yield.
    O servidor e sua thread de aceitação são encerrados mesmo se o player falhar.
    """
    try:
        supported = urlsplit(url).hostname == _CDN
    except (TypeError, ValueError) as exc:
        raise _RelayError("URL de stream inválida.") from exc
    if not supported:
        yield url
        return
    url = _validate_url(url)
    body, status, _ = _fetch(url, context="manifesto inicial")
    if status != 200 or not _is_manifest(body):
        raise _RelayError("manifesto inicial inválido; esperado HTTP 200 e #EXTM3U.")
    relay = _Relay()
    server = _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              name="animefire-stream-relay", daemon=True)
    started = False
    try:
        relay.base = f"http://127.0.0.1:{server.server_port}"
        server.relay = relay
        local_url = relay.register(url, "manifest")
        # Valida também todas as referências do master antes de iniciar o player.
        relay.rewrite(body, url)
        relay.initial = (urlsplit(local_url).path, body)
        thread.start()
        started = True
        yield local_url
    finally:
        if started:
            server.shutdown()
        server.server_close()
        if started:
            thread.join()
