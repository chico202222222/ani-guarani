"""Histórico validado, com substituição atômica e leitura do formato legado."""
import json
import os
import tempfile
from pathlib import Path


def history_path():
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    # Mantém o diretório antigo para preservar o histórico existente.
    return root / "ani-tupi" / "history.json"


def validate_sources(sources):
    """Valida a estrutura [[urls, fonte], ...] compartilhada por histórico e lista."""
    if not isinstance(sources, list) or not sources:
        raise ValueError("fontes inválidas")
    for source in sources:
        if not isinstance(source, (list, tuple)) or len(source) != 2:
            raise ValueError("fonte inválida")
        urls, name = source
        if not isinstance(urls, list) or not urls or not all(isinstance(url, str) for url in urls) or not isinstance(name, str):
            raise ValueError("URLs inválidas")


def write_json_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_history(path=None):
    path = Path(path) if path is not None else history_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("objeto JSON esperado")
        for title, entry in data.items():
            if not isinstance(title, str) or not isinstance(entry, list) or len(entry) != 2:
                raise ValueError("entrada inválida")
            sources, index = entry
            if not isinstance(sources, list) or not sources or type(index) is not int or index < 0:
                raise ValueError("episódio inválido")
            validate_sources(sources)
            if index >= max(len(urls) for urls, _ in sources):
                raise ValueError("episódio fora da lista")
        return data
    except (ValueError, OSError) as exc:
        raise RuntimeError(f"Não foi possível ler {path}: {exc}. Preserve ou renomeie o arquivo para iniciar outro histórico.") from exc


def save_history(anime, episode, sources, path=None):
    path = Path(path) if path is not None else history_path()
    data = read_history(path)
    data[anime] = [sources, episode]
    write_json_atomic(path, data)
