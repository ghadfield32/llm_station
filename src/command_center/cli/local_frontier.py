#!/usr/bin/env python3
"""CLI for the local-frontier lane — read-only preflight + health checks, no live chat call
(that's `make colibri-benchmark`, kept out of `cc` since a live run can take minutes-to-hours
per case). Registered into the main `cc` app (unlike frontier_router.py, which stays
Makefile-only because it can spend real money) since neither subcommand here has a real-world
cost: preflight only reads disk/RAM/GPU state, health only hits a loopback endpoint.

  preflight   disk/RAM/GPU headroom vs. the configured model's declared disk_footprint_gb
  health      current lane_enabled/health/selectable for every configured model

Invoke via `cc colibri-preflight` / `cc colibri-health`, or directly:
  python -m command_center.cli.local_frontier preflight
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess


def _disk_free_gb(path: str = ".") -> float:
    return round(shutil.disk_usage(path).free / (1024 ** 3), 1)


def _total_ram_gb() -> float | None:
    """Best-effort, platform-specific — never raises; a missing reading just omits the field
    rather than fabricating a number."""
    try:
        if platform.system() == "Windows":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                    ("sullAvailExtendedVirtual", ctypes.c_uint64),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return round(stat.ullTotalPhys / (1024 ** 3), 1)
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / (1024 ** 2), 1)
    except Exception:
        return None
    return None


def _gpu_info() -> list[dict]:
    """nvidia-smi if present, else empty — never fabricated, never raises. Works identically
    on native Windows and inside WSL2 (GPU passthrough exposes the same tool)."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5, check=True)
    except Exception:
        return []
    gpus = []
    for line in out.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3:
            gpus.append({"name": parts[0], "memory_total": parts[1], "memory_free": parts[2]})
    return gpus


def _preflight() -> dict:
    from ..channels.local_frontier_client import load_providers
    report: dict = {
        "disk_free_gb": _disk_free_gb("."),
        "total_ram_gb": _total_ram_gb(),
        "gpus": _gpu_info(),
    }
    try:
        cfg = load_providers()
    except Exception as exc:
        report["models"] = []
        report["config_error"] = str(exc)
        return report
    rows = []
    for model_id, model in cfg.models.items():
        headroom_gb = round(report["disk_free_gb"] - model.disk_footprint_gb, 1)
        rows.append({
            "model_id": model_id,
            "disk_footprint_gb": model.disk_footprint_gb,
            "disk_headroom_after_download_gb": headroom_gb,
            "verdict": ("insufficient" if headroom_gb < 0
                       else "tight" if headroom_gb < 100
                       else "ok"),
        })
    report["models"] = rows
    return report


def _cmd_preflight(_args: argparse.Namespace) -> int:
    print(json.dumps(_preflight(), indent=2))
    return 0


def _cmd_health(_args: argparse.Namespace) -> int:
    from ..channels.local_frontier_client import available_local_frontier_models
    print(json.dumps(available_local_frontier_models(), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="local-frontier")
    sub = parser.add_subparsers(dest="command", required=True)

    pf = sub.add_parser("preflight", help="disk/RAM/GPU headroom vs. configured model(s)")
    pf.set_defaults(func=_cmd_preflight)

    hc = sub.add_parser(
        "health", help="lane_enabled/health/selectable for every configured model")
    hc.set_defaults(func=_cmd_health)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
