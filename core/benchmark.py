"""Prueba de rendimiento propia: disco, procesador y apertura de programas, en menos de un
minuto y sin instalar nada.

No pretende competir con CrystalDiskMark o Cinebench: mide siempre lo mismo y de la misma forma
para comparar el equipo consigo mismo (antes y después de optimizar, o mes a mes).

- Disco: escritura secuencial de 256 MB con fsync, lectura de ese archivo y escrituras
  aleatorias de 4 KB con fsync durante 2 s. La lectura puede salir en parte de la caché de
  Windows; se informa igual porque es lo que nota el usuario al abrir archivos recientes.
- Procesador: SHA-256 de un bloque fijo con un hilo y con todos (hashlib suelta el GIL con
  bloques grandes, así que los hilos escalan de verdad).
- Programas: lo que tardan en estar listos el Bloc de notas y Paint
  (WaitForInputIdle), cerrándolos después.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from core.constants import APP_HOME
from core.logger import get_logger
from core.process import CommandError, Runner

log = get_logger("benchmark")

BENCH_FILE = APP_HOME / "benchmarks.json"
DISK_MB = 256
CHUNK = 4 * 1024 * 1024
RANDOM_SECONDS = 2.0
CPU_BLOCK = 8 * 1024 * 1024
CPU_ROUNDS = 12
MAX_RESULTS = 50

# Se miden programas que existen en cualquier Windows 10/11.
_APPS_SCRIPT = r"""
$out = @()
foreach ($exe in @('notepad.exe', 'mspaint.exe')) {
  try {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $p = Start-Process $exe -PassThru -WindowStyle Minimized -ErrorAction Stop
    [void]$p.WaitForInputIdle(15000)
    $ms = $sw.ElapsedMilliseconds
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    $out += @{ app = $exe; ms = $ms }
  } catch { }
}
ConvertTo-Json -InputObject @($out) -Compress
"""

ProgressFn = Callable[[float, str], None]  # (fracción 0-1, texto), como ui.worker


@dataclass
class BenchResult:
    when: str = ""
    disk_write_mbs: float | None = None
    disk_read_mbs: float | None = None
    disk_random_iops: float | None = None
    cpu_single_mbs: float | None = None
    cpu_multi_mbs: float | None = None
    threads: int = 0
    apps_ms: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def _disk(directory: Path, result: BenchResult, size_mb: int = DISK_MB) -> None:
    block = os.urandom(CHUNK)  # datos aleatorios: un SSD que comprime no hace trampa
    fd, name = tempfile.mkstemp(prefix="safeboost-bench-", dir=directory)
    path = Path(name)
    try:
        start = time.perf_counter()
        with os.fdopen(fd, "wb", buffering=0) as fh:
            for _ in range(max(1, size_mb * 1024 * 1024 // CHUNK)):
                fh.write(block)
            fh.flush()
            os.fsync(fh.fileno())
        elapsed = time.perf_counter() - start
        result.disk_write_mbs = round(size_mb / elapsed, 1)

        start = time.perf_counter()
        with path.open("rb", buffering=0) as fh:
            while fh.read(CHUNK):
                pass
        result.disk_read_mbs = round(size_mb / (time.perf_counter() - start), 1)

        small = os.urandom(4096)
        blocks = max(1, size_mb * 1024 * 1024 // 4096)
        ops = 0
        rng = random.Random(1)  # noqa: S311 - posiciones de prueba, no criptografía
        with path.open("r+b", buffering=0) as fh:
            start = time.perf_counter()
            while time.perf_counter() - start < RANDOM_SECONDS:
                fh.seek(rng.randrange(blocks) * 4096)
                fh.write(small)
                os.fsync(fh.fileno())
                ops += 1
            result.disk_random_iops = round(ops / (time.perf_counter() - start))
    finally:
        path.unlink(missing_ok=True)


def _hash_rounds(block: bytes, rounds: int) -> None:
    for _ in range(rounds):
        hashlib.sha256(block).digest()


def _cpu(result: BenchResult, threads: int | None = None) -> None:
    block = bytes(CPU_BLOCK)
    mb = CPU_BLOCK / 1024 / 1024
    start = time.perf_counter()
    _hash_rounds(block, CPU_ROUNDS)
    result.cpu_single_mbs = round(mb * CPU_ROUNDS / (time.perf_counter() - start), 1)

    count = threads or os.cpu_count() or 1
    result.threads = count
    workers = [
        threading.Thread(target=_hash_rounds, args=(block, CPU_ROUNDS)) for _ in range(count)
    ]
    start = time.perf_counter()
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    result.cpu_multi_mbs = round(mb * CPU_ROUNDS * count / (time.perf_counter() - start), 1)


def _apps(runner: Runner, result: BenchResult) -> None:
    data = runner.powershell_json(_APPS_SCRIPT, timeout=60)
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict) and isinstance(item.get("ms"), int):
            result.apps_ms[str(item.get("app"))] = item["ms"]


def run_benchmark(
    runner: Runner | None, directory: Path, progress: ProgressFn | None = None
) -> BenchResult:
    """Ejecuta las tres pruebas. Cada una es independiente: un fallo queda en `errors`."""
    result = BenchResult(when=datetime.now().isoformat(timespec="seconds"))
    steps: list[tuple[str, Callable[[], None]]] = [
        ("Midiendo el disco…", lambda: _disk(directory, result)),
        ("Midiendo el procesador…", lambda: _cpu(result)),
    ]
    if runner is not None:
        steps.append(
            ("Midiendo cuánto tardan en abrirse los programas…", lambda: _apps(runner, result))
        )
    for i, (label, step) in enumerate(steps):
        if progress:
            progress(i / len(steps), label)
        try:
            step()
        except (OSError, CommandError, ValueError) as exc:
            log.warning("benchmark_step_failed", extra={"step": label, "err": str(exc)})
            result.errors.append(f"{label.rstrip('…')}: {exc}")
    return result


def change_pct(
    before: float | None, after: float | None, higher_is_better: bool = True
) -> int | None:
    """Mejora en % (positivo = mejor) entre dos mediciones."""
    if not before or after is None:
        return None
    delta = (after - before) / before * 100
    return round(delta if higher_is_better else -delta)


class BenchStore:
    def __init__(self, path: Path = BENCH_FILE) -> None:
        self.path = path

    def load(self) -> list[BenchResult]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        known = set(BenchResult.__dataclass_fields__)
        return [
            BenchResult(**{k: v for k, v in item.items() if k in known})
            for item in raw
            if isinstance(item, dict)
        ]

    def add(self, result: BenchResult) -> None:
        items = [*self.load(), result][-MAX_RESULTS:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(i) for i in items], indent=1), encoding="utf-8")
        tmp.replace(self.path)
