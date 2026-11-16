"""Host CPU and memory sampling without a third-party dependency.

Linux reads ``/proc``; Windows calls ``kernel32`` through ``ctypes``. Anything
else falls back to ``psutil`` when it happens to be importable, and to
``CollectorError`` otherwise, so an unsupported host reports ``unknown`` instead
of a fabricated number.

CPU needs two counter snapshots: the kernel only exposes cumulative time, so
"current usage" is always a delta over a short window.
"""

import asyncio
import ctypes
import sys
import time
from pathlib import Path

from .registry import CollectorContext, CollectorError

SAMPLE_SECONDS = 0.15
PROC_STAT = Path("/proc/stat")
PROC_MEMINFO = Path("/proc/meminfo")
# /proc/meminfo reports kilobytes.
PROC_MEMINFO_UNIT = 1024


# ---------------------------------------------------------------------------
# Linux
# ---------------------------------------------------------------------------


def parse_proc_stat(text: str) -> tuple[int, int]:
    """Return ``(idle_ticks, total_ticks)`` for the aggregate ``cpu`` line.

    Idle includes ``iowait``: a disk-bound box is not CPU-bound, and counting
    iowait as busy produces spurious alerts.
    """

    line = next((row for row in text.splitlines() if row.startswith("cpu ")), "")
    fields = line.split()[1:]
    if not fields:
        raise CollectorError("proc_stat_unreadable")
    ticks = [int(value) for value in fields]
    idle = ticks[3] + (ticks[4] if len(ticks) > 4 else 0)
    return idle, sum(ticks)


def parse_meminfo(text: str) -> dict[str, int]:
    """Return ``/proc/meminfo`` as bytes, keyed without the trailing colon."""

    values: dict[str, int] = {}
    for row in text.splitlines():
        key, separator, rest = row.partition(":")
        if not separator:
            continue
        fields = rest.split()
        if fields:
            values[key.strip()] = int(fields[0]) * PROC_MEMINFO_UNIT
    return values


def memory_percent_from_meminfo(values: dict[str, int]) -> float:
    """Used memory as a percentage, preferring the kernel's own estimate."""

    total = values.get("MemTotal", 0)
    if total <= 0:
        raise CollectorError("meminfo_total_missing")
    available = values.get("MemAvailable")
    if available is None:
        available = values.get("MemFree", 0) + values.get("Buffers", 0) + values.get("Cached", 0)
    return max(0.0, min(100.0, (total - available) / total * 100))


def _linux_cpu_percent() -> float:
    idle_before, total_before = parse_proc_stat(PROC_STAT.read_text(encoding="utf-8"))
    time.sleep(SAMPLE_SECONDS)
    idle_after, total_after = parse_proc_stat(PROC_STAT.read_text(encoding="utf-8"))
    total_delta = total_after - total_before
    if total_delta <= 0:
        raise CollectorError("proc_stat_no_delta")
    busy_delta = total_delta - (idle_after - idle_before)
    return max(0.0, min(100.0, busy_delta / total_delta * 100))


def _linux_memory_percent() -> float:
    return memory_percent_from_meminfo(parse_meminfo(PROC_MEMINFO.read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------


class _FileTime(ctypes.Structure):
    _fields_ = [
        ("low", ctypes.c_uint32),
        ("high", ctypes.c_uint32),
    ]


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_uint32),
        ("load", ctypes.c_uint32),
        ("total_phys", ctypes.c_uint64),
        ("avail_phys", ctypes.c_uint64),
        ("total_page_file", ctypes.c_uint64),
        ("avail_page_file", ctypes.c_uint64),
        ("total_virtual", ctypes.c_uint64),
        ("avail_virtual", ctypes.c_uint64),
        ("avail_extended_virtual", ctypes.c_uint64),
    ]


def _filetime_ticks(value: _FileTime) -> int:
    return (value.high << 32) | value.low


def _windows_system_times() -> tuple[int, int, int]:
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    idle, kernel, user = _FileTime(), _FileTime(), _FileTime()
    ok = kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
    if not ok:
        raise CollectorError("GetSystemTimes_failed")
    return _filetime_ticks(idle), _filetime_ticks(kernel), _filetime_ticks(user)


def _windows_cpu_percent() -> float:
    idle_before, kernel_before, user_before = _windows_system_times()
    time.sleep(SAMPLE_SECONDS)
    idle_after, kernel_after, user_after = _windows_system_times()
    # Kernel time already contains idle time, so total is kernel + user.
    total_delta = (kernel_after - kernel_before) + (user_after - user_before)
    if total_delta <= 0:
        raise CollectorError("system_times_no_delta")
    busy_delta = total_delta - (idle_after - idle_before)
    return max(0.0, min(100.0, busy_delta / total_delta * 100))


def _windows_memory_percent() -> float:
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    status = _MemoryStatus()
    status.length = ctypes.sizeof(_MemoryStatus)
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise CollectorError("GlobalMemoryStatusEx_failed")
    return max(0.0, min(100.0, float(status.load)))


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------


def _psutil_percent(kind: str) -> float:
    try:
        import psutil
    except ImportError as exc:
        raise CollectorError("unsupported_platform") from exc
    value = psutil.cpu_percent(interval=SAMPLE_SECONDS) if kind == "cpu" else None
    if value is None:
        value = psutil.virtual_memory().percent
    return float(value)


def _has_proc() -> bool:
    return sys.platform.startswith("linux") and PROC_STAT.exists()


def cpu_percent() -> tuple[float, str]:
    """Return ``(percent, source)`` where source names the sampling backend."""

    if _has_proc():
        return _linux_cpu_percent(), "proc"
    if sys.platform == "win32":
        return _windows_cpu_percent(), "kernel32"
    return _psutil_percent("cpu"), "psutil"


def memory_percent() -> tuple[float, str]:
    if _has_proc() and PROC_MEMINFO.exists():
        return _linux_memory_percent(), "proc"
    if sys.platform == "win32":
        return _windows_memory_percent(), "kernel32"
    return _psutil_percent("memory"), "psutil"


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------


async def cpu_usage(ctx: CollectorContext) -> dict:
    percent, source = await asyncio.to_thread(cpu_percent)
    return {"percent": round(percent, 1), "source": source}


async def memory_usage(ctx: CollectorContext) -> dict:
    percent, source = await asyncio.to_thread(memory_percent)
    return {"percent": round(percent, 1), "source": source}
