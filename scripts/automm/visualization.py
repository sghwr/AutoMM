"""图表登记、自动质量检查与视觉复核状态。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .common import (
    config_section,
    hash_json,
    read_yaml,
    relative,
    resolve_project_path,
    utc_now,
    write_json,
    write_yaml,
)
from .problems import problem_dir


def figure_manifest_path(problem_id: str) -> Path:
    return problem_dir(problem_id) / "figures.yaml"


def stable_figure_id(
    *,
    problem_id: str,
    question_id: str,
    kind: str,
    title: str,
    source_hash: str,
    x: str | None,
    y: list[str],
    style: dict[str, Any],
) -> str:
    payload = {
        "problem_id": problem_id,
        "question_id": question_id,
        "kind": kind,
        "title": title,
        "source_hash": source_hash,
        "x": x,
        "y": y,
        "style_hash": hash_json(style),
    }
    slug = "".join(char if char.isalnum() else "_" for char in kind.lower()).strip("_") or "chart"
    return f"{question_id}_fig_{slug}_{hash_json(payload)[:10]}"


def inspect_png(path: Path, problem_id: str, question_id: str) -> dict[str, Any]:
    config = config_section("visualization", problem_id, question_id)
    quality = config.get("quality", {})
    minimum_width = int(quality.get("minimum_width_px", 800))
    minimum_height = int(quality.get("minimum_height_px", 480))
    errors: list[str] = []
    warnings: list[str] = []
    with Image.open(path) as image:
        image.load()
        width, height = image.size
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    if width < minimum_width or height < minimum_height:
        errors.append(f"分辨率 {width}x{height} 低于 {minimum_width}x{minimum_height}")
    if rgb.size == 0 or np.ptp(rgb.astype(np.int16), axis=(0, 1)).max() < 3:
        errors.append("图像为空或近似纯色")
    border = np.concatenate((rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]), axis=0)
    dark_ratio = float(np.mean(np.mean(border, axis=1) < 32))
    if dark_ratio > float(quality.get("maximum_dark_border_ratio", 0.35)):
        warnings.append("图像边界暗像素比例较高，可能存在裁切或边框异常")
    report = {
        "checked_at": utc_now(),
        "path": relative(path),
        "width": width,
        "height": height,
        "nonblank": not any("纯色" in item for item in errors),
        "dark_border_ratio": dark_ratio,
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
    }
    write_json(path.with_suffix(".quality.json"), report)
    return report


def register_figure(problem_id: str, item: dict[str, Any]) -> dict[str, Any]:
    path = figure_manifest_path(problem_id)
    manifest = read_yaml(path, {"figures": []})
    figures = manifest.setdefault("figures", [])
    figures[:] = [old for old in figures if old.get("stable_id") != item["stable_id"]]
    figures.append(item)
    write_yaml(path, manifest)
    return item


def record_figure_review(problem_id: str, stable_id: str, status: str, reason: str) -> dict[str, Any]:
    if status not in {"passed", "needs_revision"}:
        raise ValueError("图表视觉复核状态只能是 passed 或 needs_revision")
    if not reason.strip():
        raise ValueError("图表视觉复核必须说明理由")
    path = figure_manifest_path(problem_id)
    manifest = read_yaml(path, {"figures": []})
    item = next((entry for entry in manifest.get("figures", []) if entry.get("stable_id") == stable_id), None)
    if item is None:
        raise KeyError(f"图表不存在：{stable_id}")
    resolve_project_path(item["path"], must_exist=True)
    item["visual_review"] = {"status": status, "reason": reason, "reviewed_at": utc_now()}
    write_yaml(path, manifest)
    return item
