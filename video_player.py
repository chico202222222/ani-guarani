import shutil
import subprocess
from urllib.parse import urlsplit


def play_video(url: str, debug=False) -> None:
    if not isinstance(url, str) or urlsplit(url).scheme not in {"http", "https"} or not urlsplit(url).netloc:
        raise ValueError("A fonte retornou uma URL de vídeo inválida (esperado HTTP/HTTPS).")
    if not shutil.which("mpv"):
        raise RuntimeError("mpv não encontrado no PATH. Instale-o para reproduzir vídeos.")
    result = subprocess.run(["mpv", "--fullscreen", "--cursor-autohide-fs-only", "--", url], check=False)
    if result.returncode:
        raise RuntimeError(f"mpv terminou com código {result.returncode}. A URL pode não ser reproduzível.")
