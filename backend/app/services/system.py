"""Real host metrics: psutil for CPU/RAM, NVML for the GPU (0 when unavailable)."""
from __future__ import annotations

import threading
import time
from datetime import timedelta
from typing import Any

import psutil
from sqlmodel import delete

from app.db import session_scope
from app.models import PredictionLog, SystemMetric
from app.services.hub import hub
from app.utils import utcnow

SAMPLE_EVERY_S = 2
PERSIST_EVERY_S = 10
RETENTION_DAYS = 8


class SystemMonitor:
    def __init__(self) -> None:
        self.latest: dict[str, Any] = {"cpu": 0.0, "ram": 0.0, "gpu": 0.0, "ram_used_gb": 0.0, "ram_total_gb": 0.0,
                                       "gpu_mem_used_gb": 0.0, "gpu_mem_total_gb": 0.0, "cpu_count": psutil.cpu_count() or 1,
                                       "process_cpu": 0.0, "process_ram_mb": 0.0, "gpu_name": None, "ts": None}
        self._stop = threading.Event()
        self._handle = None
        self._proc = psutil.Process()
        self.started_at = time.time()
        self._init_gpu()

    def _init_gpu(self) -> None:
        try:
            import pynvml

            pynvml.nvmlInit()
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            name = pynvml.nvmlDeviceGetName(self._handle)
            self.latest["gpu_name"] = name.decode() if isinstance(name, bytes) else str(name)
        except Exception:  # noqa: BLE001 - no NVIDIA GPU / driver
            self._handle = None

    def _gpu(self) -> tuple[float, float, float]:
        if self._handle is None:
            return 0.0, 0.0, 0.0
        try:
            import pynvml

            util = pynvml.nvmlDeviceGetUtilizationRates(self._handle).gpu
            mem = pynvml.nvmlDeviceGetMemoryInfo(self._handle)
            return float(util), mem.used / 1e9, mem.total / 1e9
        except Exception:  # noqa: BLE001
            return 0.0, 0.0, 0.0

    def sample(self) -> dict[str, Any]:
        vm = psutil.virtual_memory()
        gpu, gpu_used, gpu_total = self._gpu()
        count = psutil.cpu_count() or 1
        self.latest = {
            "cpu": round(psutil.cpu_percent(interval=None), 1),
            "ram": round(vm.percent, 1),
            "gpu": round(gpu, 1),
            "ram_used_gb": round((vm.total - vm.available) / 1e9, 2),
            "ram_total_gb": round(vm.total / 1e9, 2),
            "gpu_mem_used_gb": round(gpu_used, 2),
            "gpu_mem_total_gb": round(gpu_total, 2),
            "cpu_count": count,
            "process_cpu": round(self._proc.cpu_percent(interval=None) / count, 1),
            "process_ram_mb": round(self._proc.memory_info().rss / 1e6, 1),
            "gpu_name": self.latest.get("gpu_name"),
            "ts": utcnow().isoformat() + "Z",
        }
        return self.latest

    def persist(self) -> None:
        d = self.latest
        with session_scope() as s:
            s.add(SystemMetric(ts=utcnow(), cpu=d["cpu"], ram=d["ram"], gpu=d["gpu"], ram_used_gb=d["ram_used_gb"],
                               ram_total_gb=d["ram_total_gb"], gpu_mem_used_gb=d["gpu_mem_used_gb"],
                               gpu_mem_total_gb=d["gpu_mem_total_gb"], cpu_count=d["cpu_count"]))
            s.commit()

    def prune(self) -> None:
        cutoff = utcnow() - timedelta(days=RETENTION_DAYS)
        with session_scope() as s:
            s.exec(delete(SystemMetric).where(SystemMetric.ts < cutoff))
            s.exec(delete(PredictionLog).where(PredictionLog.ts < cutoff))
            s.commit()

    def start(self) -> None:
        psutil.cpu_percent(interval=None)  # prime the counters
        self._proc.cpu_percent(interval=None)

        def loop() -> None:
            tick = 0
            while not self._stop.wait(SAMPLE_EVERY_S):
                tick += 1
                try:
                    data = self.sample()
                    hub.publish("system", {"type": "system", **data})
                    if tick % (PERSIST_EVERY_S // SAMPLE_EVERY_S) == 0:
                        self.persist()
                    if tick % 1800 == 0:
                        self.prune()
                except Exception:  # noqa: BLE001
                    pass

        threading.Thread(target=loop, name="system-monitor", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()


system_monitor = SystemMonitor()
