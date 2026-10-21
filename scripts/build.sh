#!/usr/bin/env bash
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd -- "$root"
if [[ -n "${ANI_GUARANI_PYTHON:-}" ]]; then
    python=$ANI_GUARANI_PYTHON
elif [[ -x "$root/.venv/bin/python" ]]; then
    python="$root/.venv/bin/python"
elif [[ -x "$root/venv/bin/python" ]]; then
    python="$root/venv/bin/python"
else
    python=python3
fi
command -v -- "$python" >/dev/null 2>&1 || { printf 'Erro: Python não encontrado.\n' >&2; exit 1; }
"$python" -c 'import PyInstaller' 2>/dev/null || {
    printf 'Erro: instale requirements-build.txt no ambiente Python escolhido.\n' >&2
    exit 1
}
printf 'Gerando executável ani-guarani…\n'
"$python" -m PyInstaller --noconfirm --clean --onefile --name ani-guarani \
    --collect-submodules plugins --collect-submodules selenium.webdriver \
    --add-data 'plugins:plugins' \
    --add-data 'LICENSE:.' --add-data 'LICENSES:LICENSES' \
    --add-data 'THIRD_PARTY_NOTICES.md:.' main.py
printf 'Build concluído: %s/dist/ani-guarani\nO PATH e o ~/.bashrc não foram alterados.\n' "$root"
