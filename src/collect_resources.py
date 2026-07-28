from __future__ import annotations

import json
import os


def main() -> None:
    print(json.dumps({"cpu_count": os.cpu_count(), "gpu": "manual"}, ensure_ascii=False))


if __name__ == "__main__":
    main()

