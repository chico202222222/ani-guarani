import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

import requests

from plugins.utils import BLOGGER_USER_AGENT
from stream_proxy import animefire_stream


CLOUD_REFERER = "https://animesonline.cloud/"
CLOUD_CDNS = {"aniplay.online", "mangas.cloud", "animeq.online", "animeflix.blog"}


def ensure_media_exists(url, referer):
    """Falha cedo se o CDN responder 404/410, em vez de abrir o mpv numa tela de erro.

    Só um "não existe" definitivo bloqueia; erros de rede e outros status seguem
    para o mpv, que sabe lidar com redirecionamentos e limites do servidor.
    """
    try:
        with requests.get(url, headers={"Referer": referer, "Range": "bytes=0-0"},
                          timeout=(5, 10), stream=True, allow_redirects=False) as response:
            status = response.status_code
    except requests.RequestException:
        return
    if status in (404, 410):
        raise RuntimeError(f"O vídeo não existe mais no CDN (HTTP {status}). Tente outra fonte ou episódio.")


def play_video(url: str, debug=False) -> None:
    if not isinstance(url, str) or urlsplit(url).scheme not in {"http", "https"} or not urlsplit(url).netloc:
        raise ValueError("A fonte retornou uma URL de vídeo inválida (esperado HTTP/HTTPS).")
    if not shutil.which("mpv"):
        raise RuntimeError("mpv não encontrado no PATH. Instale-o para reproduzir vídeos.")
    # Não depende de ativar o venv nem do yt-dlp antigo instalado pela distribuição.
    search_path = os.pathsep.join((str(Path(sys.executable).parent), os.environ.get("PATH", "")))
    extractor = shutil.which("yt-dlp", path=search_path)
    command = ["mpv", "--fullscreen", "--cursor-autohide-fs-only"]
    if urlsplit(url).hostname in CLOUD_CDNS:
        # Esses CDNs da fonte Cloud recusam mídia sem o Referer do site.
        command.append(f"--referrer={CLOUD_REFERER}")
        ensure_media_exists(url, CLOUD_REFERER)
    if (urlsplit(url).hostname or "").endswith(".googlevideo.com"):
        # URLs do Blogger só funcionam com o User-Agent usado para obtê-las.
        command.append(f"--user-agent={BLOGGER_USER_AGENT}")
    if extractor:
        command.append(f"--script-opts=ytdl_hook-ytdl_path={extractor}")
        logging.getLogger(__name__).debug("Extrator de vídeo: %s", extractor)
    else:
        logging.getLogger(__name__).warning(
            "yt-dlp não encontrado. Instale requirements.txt no ambiente do projeto; players incorporados podem falhar."
        )
    with animefire_stream(url) as playback_url:
        if playback_url != url:
            # O relay entrega HLS real; não precisamos invocar um extrator de páginas.
            command.append("--ytdl=no")
        command.extend(["--", playback_url])
        result = subprocess.run(command, check=False)
    if result.returncode:
        raise RuntimeError(
            f"mpv terminou com código {result.returncode}. A URL pode não ser reproduzível. "
            "Se houver erro do ytdl_hook, atualize o yt-dlp no ambiente do projeto "
            "(.venv/bin/python -m pip install --upgrade yt-dlp) e tente novamente. "
            "O player também pode estar indisponível ou incompatível com o extrator."
        )
