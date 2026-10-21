"""Barra de carregamento animada para operações demoradas, só em terminal interativo."""
import logging
import os
import shutil
import sys
import threading

FRAME_SECONDS = 0.06
BAR_WIDTH = 24
_PARTIAL = "░▏▎▍▌▋▊▉"
_ASCII = dict(full="#", empty="-", sweep="=", left="[", right="]", partial="")


def _interactive(stream):
    return stream.isatty() and os.environ.get("TERM") != "dumb"


class Loading:
    """Mostra `message` com uma barra enquanto o bloco `with` roda.

    Sem total conhecido a barra "vai e volta"; com `update(feitos, total)` ela
    enche de verdade, suavizada entre um passo e outro. Fora de um terminal, ou
    com TERM=dumb, só escreve a mensagem uma vez, sem códigos de controle.
    """

    def __init__(self, message, stream=None):
        self.message = message
        self.stream = stream or sys.stderr
        self.animated = _interactive(self.stream)
        self.color = "NO_COLOR" not in os.environ
        self.unicode = (getattr(self.stream, "encoding", None) or "").lower().replace("-", "") == "utf8"
        self._target = None  # fração concluída; None enquanto o total é desconhecido
        self._counts = ""
        self._shown = 0.0
        self._tick = 0
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._patched = []

    def update(self, done, total):
        with self._lock:
            self._target = min(1.0, done / total) if total else None
            self._counts = f" {done}/{total}" if total else ""

    def __enter__(self):
        if not self.animated:
            print(self.message, file=self.stream, flush=True)
            return self
        self._write("\033[?25l")
        self._guard_logging()
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        if self._thread:
            self._stop.set()
            self._thread.join()
            self._restore_logging()
            with self._lock:
                self._write("\r\033[K\033[?25h")
        return False

    def _write(self, text):
        self.stream.write(text)
        self.stream.flush()

    def _animate(self):
        while not self._stop.wait(FRAME_SECONDS):
            with self._lock:
                self._write("\r\033[K" + self._frame())
                self._tick += 1

    def _glyphs(self):
        if self.unicode:
            return dict(full="█", empty="░", sweep="▒", left="▕", right="▏", partial=_PARTIAL)
        return _ASCII

    def _frame(self):
        g = self._glyphs()
        cells = [g["empty"]] * BAR_WIDTH
        if self._target is None:
            # Bloco de 4 células quicando de ponta a ponta.
            span = BAR_WIDTH - 4
            pos = self._tick % (2 * span)
            pos = pos if pos <= span else 2 * span - pos
            cells[pos:pos + 4] = [g["full"]] * 4
            tail = ""
        else:
            # Aproxima-se do alvo a cada quadro; nunca recua nem passa de 100%.
            gap = self._target - self._shown
            self._shown += max(gap * 0.25, min(gap, 0.004)) if gap > 0 else 0
            exact = self._shown * BAR_WIDTH
            full = int(exact)
            cells[:full] = [g["full"]] * full
            if full < BAR_WIDTH and g["partial"]:
                cells[full] = g["partial"][int((exact - full) * 8)] if exact > full else g["empty"]
            # Brilho passando pela parte vazia: mostra que ainda está trabalhando.
            sweep = self._tick % (BAR_WIDTH + 6) - 3
            for i in range(sweep, sweep + 3):
                if full < i < BAR_WIDTH and cells[i] == g["empty"]:
                    cells[i] = g["sweep"]
            tail = f"{int(self._shown * 100):3d}%{self._counts}"
        bar = g["left"] + "".join(cells) + g["right"]
        room = max(10, shutil.get_terminal_size().columns - len(bar) - len(tail) - 3)
        message = self.message if len(self.message) <= room else self.message[:room - 1] + "…"
        line = f"{bar} {tail} {message}" if tail else f"{bar} {message}"
        return f"\033[36m{line}\033[0m" if self.color else line

    def _guard_logging(self):
        """Faz avisos do `logging` limparem a barra antes de escrever, em vez de se misturarem a ela."""
        for handler in logging.getLogger().handlers:
            if not isinstance(handler, logging.StreamHandler) or getattr(handler, "stream", None) is not self.stream:
                continue
            original = handler.emit

            def emit(record, original=original):
                with self._lock:
                    self._write("\r\033[K")
                    original(record)

            handler.emit = emit
            self._patched.append(handler)

    def _restore_logging(self):
        for handler in self._patched:
            handler.__dict__.pop("emit", None)
        self._patched.clear()
