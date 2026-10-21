import re
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

import requests

import stream_proxy as proxy

ROOT = "https://akumast.net/i/naruto/h.jpg"
MASTER = b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000000\n720/odd-name.jpg\n'
MEDIA = b'#EXTM3U\n#EXTINF:6,\nsegment.jpg\n#EXT-X-ENDLIST\n'
MP4 = b'\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso6'


class Response:
    def __init__(self, body=b"", status=200, headers=None, chunks=None):
        self.body = body
        self.status_code = status
        self.headers = headers or {"Content-Type": "image/jpeg"}
        self.closed = False
        self.chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def iter_content(self, chunk_size):
        if self.chunks is not None:
            yield from self.chunks
        else:
            for offset in range(0, len(self.body), chunk_size):
                yield self.body[offset:offset + chunk_size]


class StreamProxyTests(unittest.TestCase):
    def setUp(self):
        # Nem o proxy HTTP do ambiente deve ser usado para os testes locais.
        self.opener = build_opener(ProxyHandler({}))
        self.responses = []

    def response(self, *args, **kwargs):
        response = Response(*args, **kwargs)
        self.responses.append(response)
        return response

    def request(self, url, method="GET", headers=None):
        with self.opener.open(Request(url, method=method, headers=headers or {}), timeout=3) as result:
            return result.status, dict(result.headers), result.read()

    def assert_http_error(self, url, status, **kwargs):
        with self.assertRaises(HTTPError) as caught:
            self.request(url, **kwargs)
        try:
            self.assertEqual(caught.exception.code, status)
            return caught.exception.read().decode()
        finally:
            caught.exception.close()

    def tearDown(self):
        self.assertTrue(all(response.closed for response in self.responses))

    def test_other_hosts_pass_through_without_network_or_server(self):
        urls = ["https://example.org/video.mp4", "https://akumast.net.evil/i/h.jpg",
                "https://sub.akumast.net/i/h.jpg", "https://127.0.0.1/i/h.jpg"]
        with patch.object(proxy.requests, "get") as get, patch.object(proxy, "_Server") as server:
            for url in urls:
                with proxy.animefire_stream(url) as result:
                    self.assertEqual(result, url)
        get.assert_not_called()
        server.assert_not_called()

    def test_supported_host_requires_https_default_port_no_credentials_and_i_prefix(self):
        urls = ["http://akumast.net/i/h.jpg", "https://akumast.net:80/i/h.jpg",
                "https://akumast.net:444/i/h.jpg", "https://user@akumast.net/i/h.jpg",
                "https://user:pass@akumast.net/i/h.jpg", "https://akumast.net/outside/h.jpg",
                "https://akumast.net/i", "https://akumast.net/i/../private",
                "https://akumast.net/i/%2e%2e/private", "https://akumast.net/i/%252e%252e/private",
                "https://akumast.net/i/%5cprivate", "https://akumast.net/i/h.jpg#fragment",
                "https://akumast.net/i/\nh.jpg", "https://akumast.net/i/h.jpg?x=\r\nsecret",
                "https://akumast.net:/i/h.jpg", "https://akumast.net:invalid/i/h.jpg"]
        with patch.object(proxy.requests, "get") as get:
            for url in urls:
                with self.subTest(url=url), self.assertRaisesRegex(RuntimeError, "URL recusada"):
                    with proxy.animefire_stream(url):
                        self.fail("URL inválida publicada")
        get.assert_not_called()

    def test_explicit_port_443_is_accepted_and_requests_are_safe(self):
        with patch.object(proxy.requests, "get", return_value=self.response(MEDIA)) as get:
            with proxy.animefire_stream(ROOT.replace("akumast.net", "akumast.net:443")) as local:
                self.assertTrue(local.startswith("http://127.0.0.1:"))
                self.assertTrue(local.endswith(".m3u8"))
                self.request(local)
        get.assert_called_once()
        self.assertEqual(get.call_args.args, (ROOT,))
        options = get.call_args.kwargs
        self.assertEqual(options["timeout"], proxy.REQUEST_TIMEOUT)
        self.assertIs(options["verify"], True)
        self.assertIs(options["allow_redirects"], False)
        self.assertIs(options["stream"], True)
        self.assertEqual(options["headers"]["Accept-Encoding"], "identity")

    def test_preflight_404_is_synchronous_readable_and_closes_response(self):
        with patch.object(proxy.requests, "get", return_value=self.response(status=404)), patch.object(
                proxy, "_Server") as server:
            with self.assertRaisesRegex(RuntimeError, "manifesto inicial: HTTP 404.*indisponível"):
                with proxy.animefire_stream(ROOT):
                    self.fail("Preflight não bloqueou o player")
        server.assert_not_called()

    def test_redirects_are_not_followed_even_to_same_host(self):
        for location in ["https://127.0.0.1/secret", "https://akumast.net/i/next.jpg"]:
            with self.subTest(location=location), patch.object(
                    proxy.requests, "get", return_value=self.response(status=302, headers={"Location": location})) as get:
                with self.assertRaisesRegex(RuntimeError, "HTTP 302.*redirecionamento recusado"):
                    with proxy.animefire_stream(ROOT):
                        self.fail("Redirect aceito")
                get.assert_called_once()
                self.assertFalse(get.call_args.kwargs["allow_redirects"])

    def test_preflight_requires_status_200_and_extm3u_not_mime_or_extension(self):
        for body, status in [(b"<html>not a playlist</html>", 200), (b"\xff\xd8jpeg", 200),
                             (MEDIA, 206), (b"", 200)]:
            with self.subTest(body=body, status=status), patch.object(
                    proxy.requests, "get", return_value=self.response(body, status)):
                with self.assertRaisesRegex(RuntimeError, "manifesto inicial inválido"):
                    with proxy.animefire_stream(ROOT):
                        self.fail("Manifesto inválido aceito")

    def test_network_errors_are_contextual_and_do_not_expose_exception_text(self):
        for error in [requests.Timeout("private-token"), requests.ConnectionError("private-token"),
                      requests.exceptions.SSLError("private-token")]:
            with self.subTest(error=type(error)), patch.object(proxy.requests, "get", side_effect=error):
                with self.assertRaisesRegex(RuntimeError, "manifesto inicial: falha de rede") as caught:
                    with proxy.animefire_stream(ROOT):
                        self.fail("Falha de rede ignorada")
                self.assertNotIn("private-token", str(caught.exception))
                self.assertIs(caught.exception.__cause__, error)

    def test_master_and_nested_jpeg_playlists_are_rewritten_and_mp4_is_normalized(self):
        variant = "https://akumast.net/i/naruto/720/odd-name.jpg"
        segment = "https://akumast.net/i/naruto/720/segment.jpg"
        upstream = {ROOT: MASTER, variant: MEDIA, segment: MP4}

        def fetch(url, **kwargs):
            return self.response(upstream[url])

        with patch.object(proxy.requests, "get", side_effect=fetch) as get:
            with proxy.animefire_stream(ROOT) as local:
                status, headers, master = self.request(local)
                self.assertEqual(status, 200)
                self.assertEqual(headers["Content-Type"], "application/vnd.apple.mpegurl")
                self.assertNotIn(b"akumast", master)
                nested = master.decode().splitlines()[-1]
                self.assertTrue(nested.endswith(".m3u8"))
                self.assertNotIn("odd-name", nested)
                status, headers, media = self.request(nested)
                self.assertEqual(headers["Content-Type"], "application/vnd.apple.mpegurl")
                binary_url = media.decode().splitlines()[2]
                self.assertTrue(binary_url.endswith(".mp4"))
                status, headers, body = self.request(binary_url)
                self.assertEqual((status, headers["Content-Type"], body), (200, "video/mp4", MP4))
        self.assertEqual([call.args[0] for call in get.call_args_list], [ROOT, variant, segment])

    def test_uri_attributes_relative_absolute_and_protocol_relative_are_rewritten(self):
        master = b'''#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",URI="audio.jpg?sig=a&n=2"
#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=100,URI="//akumast.net/i/iframes.jpg"
#EXT-X-RENDITION-REPORT:URI="https://akumast.net:443/i/report.jpg"
#EXT-X-SESSION-KEY:METHOD=AES-128,URI="/i/key.jpg"
#EXT-X-STREAM-INF:BANDWIDTH=10,AUDIO="a"
https://akumast.net/i/video.jpg
'''
        media = b'''#EXTM3U
#EXT-X-MAP:URI="init.jpg",BYTERANGE="20@0"
#EXT-X-KEY:METHOD=AES-128,URI="/i/key.jpg",IV=0x00
#EXTINF:6,
/i/segment.jpg?signature=private
'''
        with patch.object(proxy.requests, "get", side_effect=[
                self.response(master), self.response(media), self.response(MP4), self.response(b"1234567890123456")]) as get:
            with proxy.animefire_stream(ROOT) as local:
                _, _, body = self.request(local)
                attrs = re.findall(r'URI="([^"]+)"', body.decode())
                self.assertEqual(len(attrs), 4)
                self.assertTrue(all(url.endswith(".m3u8") for url in attrs[:3]))
                self.assertTrue(attrs[3].endswith(".mp4"))
                video = body.decode().splitlines()[-1]
                _, _, rewritten = self.request(video)
                self.assertNotIn(b"private", rewritten)
                self.assertIn(b'BYTERANGE="20@0"', rewritten)
                self.assertIn(b"IV=0x00", rewritten)
                init, key = re.findall(r'URI="([^"]+)"', rewritten.decode())
                self.assertEqual(self.request(init)[1]["Content-Type"], "video/mp4")
                self.assertEqual(self.request(key)[1]["Content-Type"], "application/octet-stream")
        self.assertEqual([call.args[0] for call in get.call_args_list],
                         [ROOT, "https://akumast.net/i/video.jpg", "https://akumast.net/i/init.jpg",
                          "https://akumast.net/i/key.jpg"])

    def test_unhinted_jpeg_is_detected_from_bytes_and_not_its_mime(self):
        # Mesmo um nome que não sugere HLS recebe MIME e conteúdo de manifesto.
        with patch.object(proxy.requests, "get", side_effect=[
                self.response(b"#EXTM3U\nunknown.jpg\n"), self.response(MEDIA), self.response(MEDIA)]) as get:
            with proxy.animefire_stream(ROOT) as local:
                child = self.request(local)[2].decode().splitlines()[-1]
                self.assertTrue(child.endswith(".mp4"))
                with self.opener.open(child, timeout=3) as result:
                    self.assertTrue(result.geturl().endswith(".m3u8"))
                    self.assertEqual(urlsplit(result.geturl()).netloc, urlsplit(local).netloc)
                    self.assertEqual(result.headers["Content-Type"], "application/vnd.apple.mpegurl")
                    body = result.read()
                self.assertTrue(body.startswith(b"#EXTM3U"))
                self.assertIn(b"http://127.0.0.1:", body)
        self.assertEqual(get.call_count, 3)
        self.assertEqual(get.call_args_list[1].args, get.call_args_list[2].args)

    def test_manifest_name_hints_and_utf8_bom(self):
        for name in ["h.jpg", "master.jpg", "1080.jpg", "720p.jpg", "quality-480.jpg", "main.m3u8"]:
            with self.subTest(name=name), patch.object(proxy.requests, "get", return_value=self.response(
                    b"\xef\xbb\xbf#EXTM3U\n" + name.encode() + b"\n")):
                with proxy.animefire_stream(ROOT) as local:
                    body = self.request(local)[2]
                    self.assertTrue(body.startswith(b"#EXTM3U\n"))
                    self.assertTrue(body.decode().splitlines()[-1].endswith(".m3u8"))

    def test_unsafe_manifest_references_fail_before_yield_without_fetching_them(self):
        targets = ["http://akumast.net/i/a.jpg", "https://evil.test/i/a.jpg",
                   "http://127.0.0.1:80/private", "//localhost/private", "file:///etc/passwd",
                   "data:text/plain,secret", "https://user@akumast.net/i/a.jpg",
                   "https://akumast.net:8443/i/a.jpg", "https://akumast.net/private",
                   "https://akumast.net/i/%2e%2e/private", "../../../private"]
        for target in targets:
            for line in [target, f'#EXT-X-MAP:URI="{target}"', f'#EXT-X-KEY:URI="{target}"',
                         f'#EXT-X-MEDIA:URI="{target}"']:
                with self.subTest(line=line), patch.object(proxy.requests, "get", return_value=self.response(
                        ("#EXTM3U\n" + line + "\n").encode())) as get:
                    with self.assertRaisesRegex(RuntimeError, "URL recusada"):
                        with proxy.animefire_stream(ROOT):
                            self.fail("Referência insegura publicada")
                    get.assert_called_once()

    def test_nested_unsafe_references_and_redirects_return_502_without_following(self):
        for response in [self.response(b"#EXTM3U\nhttp://127.0.0.1/secret\n"),
                         self.response(status=301, headers={"Location": "https://evil.test/"})]:
            with self.subTest(status=response.status_code), patch.object(proxy.requests, "get", side_effect=[
                    self.response(MASTER), response]) as get:
                with proxy.animefire_stream(ROOT) as local:
                    child = self.request(local)[2].decode().splitlines()[-1]
                    self.assert_http_error(child, 502)
                self.assertEqual(get.call_count, 2)

    def test_range_forwarding_206_and_head_have_correct_headers(self):
        partial = MP4[4:12]
        with patch.object(proxy.requests, "get", side_effect=[self.response(MEDIA),
                self.response(partial, 206, {"Content-Range": "bytes 4-11/24"}),
                self.response(MP4)]) as get:
            with proxy.animefire_stream(ROOT) as local:
                segment = self.request(local)[2].decode().splitlines()[2]
                status, headers, body = self.request(segment, headers={"Range": "bytes=4-11"})
                self.assertEqual((status, body), (206, partial))
                self.assertEqual(headers["Content-Range"], "bytes 4-11/24")
                self.assertEqual(headers["Content-Length"], str(len(partial)))
                self.assertEqual(headers["Content-Type"], "video/mp4")
                self.assertEqual(get.call_args.kwargs["headers"]["Range"], "bytes=4-11")
                status, headers, body = self.request(segment, method="HEAD")
                self.assertEqual((status, body), (200, b""))
                self.assertEqual(headers["Content-Length"], str(len(MP4)))

    def test_head_manifest_preserves_preflight_for_get(self):
        with patch.object(proxy.requests, "get", return_value=self.response(MEDIA)) as get:
            with proxy.animefire_stream(ROOT) as local:
                status, headers, body = self.request(local, method="HEAD")
                self.assertEqual((status, body), (200, b""))
                self.assertEqual(headers["Content-Type"], "application/vnd.apple.mpegurl")
                _, _, body = self.request(local)
                self.assertEqual(headers["Content-Length"], str(len(body)))
        get.assert_called_once()

    def test_range_on_manifest_refetches_full_content_before_rewriting(self):
        with patch.object(proxy.requests, "get", side_effect=[self.response(MEDIA),
                self.response(MEDIA[:10], 206, {"Content-Range": "bytes 0-9/55"}),
                self.response(MEDIA)]) as get:
            with proxy.animefire_stream(ROOT) as local:
                status, headers, body = self.request(local, headers={"Range": "bytes=0-9"})
                self.assertEqual(status, 200)
                self.assertNotIn("Content-Range", headers)
                self.assertIn(b"#EXT-X-ENDLIST", body)
        self.assertEqual(get.call_args_list[1].kwargs["headers"]["Range"], "bytes=0-9")
        self.assertNotIn("Range", get.call_args_list[2].kwargs["headers"])

    def test_invalid_range_and_unregistered_routes_never_trigger_network(self):
        with patch.object(proxy.requests, "get", return_value=self.response(MEDIA)) as get:
            with proxy.animefire_stream(ROOT) as local:
                for suffix in ["?url=https://evil.test/", "/https://evil.test/", "?x=1"]:
                    self.assert_http_error(local + suffix, 404)
                parts = urlsplit(local)
                self.assert_http_error(f"http://{parts.netloc}/wrong-token/unknown.mp4", 404)
                self.assert_http_error(local.replace(".m3u8", ".mp4"), 404)
                for value in ["bytes=0-1,3-4", "items=0-1", "bytes=-", "garbage"]:
                    self.assert_http_error(local, 400, headers={"Range": value})
                self.assert_http_error(local, 403, headers={"Host": "evil.test"})
        get.assert_called_once()

    def test_route_limit_and_deduplication(self):
        relay = proxy._Relay()
        relay.base = "http://127.0.0.1:1234"
        with patch.object(proxy, "MAX_ROUTES", 2):
            first = relay.register(ROOT)
            self.assertEqual(first, relay.register(ROOT))
            relay.register("https://akumast.net/i/other.jpg")
            with self.assertRaisesRegex(RuntimeError, "limite de rotas"):
                relay.register("https://akumast.net/i/third.jpg")
            self.assertEqual(len(relay.routes), 2)
            self.assertEqual(first, relay.register(ROOT))

    def test_live_manifests_are_not_cached_and_route_limit_applies_to_updates(self):
        with patch.object(proxy, "MAX_ROUTES", 2), patch.object(proxy.requests, "get", side_effect=[
                self.response(MEDIA), self.response(b"#EXTM3U\nnext.jpg\n")]) as get:
            with proxy.animefire_stream(ROOT) as local:
                self.request(local)
                self.assertIn("limite de rotas", self.assert_http_error(local, 502))
        self.assertEqual(get.call_count, 2)

    def test_media_and_manifest_body_limits_close_responses(self):
        with patch.object(proxy, "MAX_RESPONSE_BYTES", 16), patch.object(proxy.requests, "get", side_effect=[
                self.response(b"#EXTM3U\na.jpg\n"), self.response(chunks=[b"x" * 10, b"y" * 10])]):
            with proxy.animefire_stream(ROOT) as local:
                segment = self.request(local)[2].decode().splitlines()[-1]
                self.assertIn("limite de segurança", self.assert_http_error(segment, 502))
        with patch.object(proxy, "MAX_MANIFEST_BYTES", 12), patch.object(proxy.requests, "get", return_value=
                self.response(chunks=[b"#EXT", b"M3U\n", b"long playlist"])):
            with self.assertRaisesRegex(RuntimeError, "limite de segurança"):
                with proxy.animefire_stream(ROOT):
                    self.fail("Manifesto grande aceito")

    def test_iteration_errors_close_response_and_return_contextual_502(self):
        def chunks():
            yield b"some bytes"
            raise requests.ConnectionError("private-token")

        with patch.object(proxy.requests, "get", side_effect=[
                self.response(MEDIA), self.response(chunks=chunks())]):
            with proxy.animefire_stream(ROOT) as local:
                segment = self.request(local)[2].decode().splitlines()[2]
                error = self.assert_http_error(segment, 502)
                self.assertIn("recurso HLS: falha de rede", error)
                self.assertNotIn("private-token", error)

    def test_segment_404_preserves_status_and_error_is_head_safe(self):
        with patch.object(proxy.requests, "get", side_effect=[self.response(MEDIA),
                self.response(status=404), self.response(status=404)]):
            with proxy.animefire_stream(ROOT) as local:
                segment = self.request(local)[2].decode().splitlines()[2]
                self.assertIn("HTTP 404", self.assert_http_error(segment, 404))
                self.assertEqual(self.assert_http_error(segment, 404, method="HEAD"), "")

    def test_no_access_logging_contains_token(self):
        with patch.object(proxy.requests, "get", return_value=self.response(MEDIA)), patch(
                "sys.stderr") as stderr:
            with proxy.animefire_stream(ROOT) as local:
                self.request(local)
                self.assert_http_error(local + "?invalid", 404)
        stderr.write.assert_not_called()

    def test_cleanup_on_normal_exit_and_player_exception_closes_socket_and_thread(self):
        original = proxy._Server
        for fail in [False, True]:
            servers = []
            threads = []
            local = ""

            def make_server(*args, servers=servers):
                server = original(*args)
                servers.append(server)
                return server

            with self.subTest(fail=fail), patch.object(proxy, "_Server", side_effect=make_server), patch.object(
                    proxy.requests, "get", return_value=self.response(MEDIA)):
                try:
                    with proxy.animefire_stream(ROOT) as local:
                        self.assertEqual(servers[0].server_address[0], "127.0.0.1")
                        self.assertTrue(servers[0].daemon_threads)
                        threads = [thread for thread in threading.enumerate()
                                   if thread.name == "animefire-stream-relay"]
                        self.assertEqual(len(threads), 1)
                        if fail:
                            raise RuntimeError("mpv failed")
                except RuntimeError as exc:
                    self.assertTrue(fail)
                    self.assertEqual(str(exc), "mpv failed")
                self.assertFalse(threads[0].is_alive())
                self.assertEqual(servers[0].fileno(), -1)
                with self.assertRaises((URLError, ConnectionError, OSError)):
                    self.request(local)

    def test_invalid_master_references_close_bound_socket_without_starting_thread(self):
        original = proxy._Server
        servers = []

        def make_server(*args):
            server = original(*args)
            servers.append(server)
            return server

        with patch.object(proxy, "_Server", side_effect=make_server), patch.object(
                proxy.requests, "get", return_value=self.response(b"#EXTM3U\nhttps://evil.test/i/a\n")), patch.object(
                proxy.threading.Thread, "start") as start:
            with self.assertRaises(RuntimeError):
                with proxy.animefire_stream(ROOT):
                    self.fail("Manifesto inseguro aceito")
        start.assert_not_called()
        self.assertEqual(servers[0].fileno(), -1)


if __name__ == "__main__":
    unittest.main()
