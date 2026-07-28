from __future__ import annotations

import sys
from pathlib import Path

ROOT_PATH = Path(__file__).resolve().parents[1]
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))

from server.config import KaggleConfig
from server.services.kaggle_runner import KaggleRunner


def main() -> None:
    runner = KaggleRunner.__new__(KaggleRunner)
    runner.config = KaggleConfig(
        username="songhow",
        default_private=True,
        default_internet=True,
        gpu_limit=2,
        session_limit=5,
    )
    output = "Kernel version 1 successfully pushed. Please check progress at https://www.kaggle.com/code/songhow/exp-demo-001"
    assert runner._kernel_id_from_push_output(output) == "songhow/exp-demo-001"
    assert runner._slugify("Exp_Demo_001!") == "exp-demo-001"
    assert runner._last_non_empty_line("a\n\nb\n") == "b"
    print("kaggle helper test passed")


if __name__ == "__main__":
    main()
