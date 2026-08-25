"""输出本地计算资源以及 AutoMM 实际采用的并发上限。"""

from __future__ import annotations

import json
import os
import platform
import sys

import psutil
from automm.common import ROOT, read_yaml
from automm.tasks import effective_workers


def main() -> None:
    memory = psutil.virtual_memory()
    config = read_yaml(ROOT / "config" / "compute.yaml")
    print(
        json.dumps(
            {
                "platform": platform.platform(),
                "python": sys.version.split()[0],
                "cpu_logical_count": os.cpu_count(),
                "memory_available_gb": round(memory.available / 1024**3, 2),
                "configured_max": config.get("max_local_concurrent_tasks", 4),
                "memory_per_worker_gb": config.get("memory_per_worker_gb", 2),
                "effective_workers": effective_workers(),
                "monitor_policy": "concurrency_duplicate_pid_output_lock",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
