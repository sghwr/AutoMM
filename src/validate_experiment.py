from __future__ import annotations

import argparse
from pathlib import Path

import yaml


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workdir")
    args = parser.parse_args()
    workdir = Path(args.workdir)
    if not (workdir / "ACK.txt").exists():
        raise SystemExit("ACK.txt not found")
    config_path = workdir / "experiment.yaml"
    if config_path.exists():
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        entrypoint = config.get("entrypoint")
        if entrypoint and not (workdir / entrypoint).exists():
            raise SystemExit(f"entrypoint not found: {entrypoint}")
    print("ok")


if __name__ == "__main__":
    main()

