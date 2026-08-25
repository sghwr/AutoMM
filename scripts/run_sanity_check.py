"""执行可自动化的 L1/L2 sanity 检查并生成机器报告。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from automm.common import ROOT, read_json, relative, resolve_project_path, utc_now, write_json, write_text
from automm.tasks import TASK_ROOT


def numeric_values(value: Any) -> Iterable[float]:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield float(value)
    elif isinstance(value, dict):
        for item in value.values():
            yield from numeric_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from numeric_values(item)


def inspect_numeric_file(path: Path) -> dict[str, Any]:
    try:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            values = pd.read_csv(path).select_dtypes(include="number").to_numpy(dtype=float)
            tolerate_nan = True
        elif suffix == ".json":
            values = np.asarray(list(numeric_values(json.loads(path.read_text(encoding="utf-8")))), dtype=float)
            tolerate_nan = False
        elif suffix == ".npy":
            values = np.asarray(np.load(path, allow_pickle=False), dtype=float)
            tolerate_nan = False
        elif suffix == ".npz":
            with np.load(path, allow_pickle=False) as data:
                arrays = [np.asarray(data[key], dtype=float).ravel() for key in data.files]
            values = np.concatenate(arrays) if arrays else np.asarray([], dtype=float)
            tolerate_nan = False
        else:
            raise ValueError("不支持的数值文件类型")
        flat = values.ravel()
        is_inf = np.isinf(flat)
        is_nan = np.isnan(flat)
        finite_vals = flat[np.isfinite(flat)]
        if tolerate_nan:
            finite = bool(not is_inf.any())
        else:
            finite = bool(np.isfinite(flat).all()) if flat.size else True
        return {
            "path": relative(path),
            "numeric_count": int(values.size),
            "finite": finite,
            "missing_numeric_count": int(is_nan.sum()),
            "infinite_numeric_count": int(is_inf.sum()),
            "empty_numeric": values.size == 0,
            "minimum": float(finite_vals.min()) if finite_vals.size else None,
            "maximum": float(finite_vals.max()) if finite_vals.size else None,
        }
    except Exception as exc:
        return {"path": relative(path), "read_error": str(exc), "finite": False, "missing_numeric_count": 0, "infinite_numeric_count": 0}


def build_report(directory: Path, task_id: str | None) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    task_status: dict[str, Any] | None = None
    if task_id:
        task_status = read_json(TASK_ROOT / task_id / "status.json", default={})
        if task_status.get("status") != "succeeded":
            feasible = bool(task_status.get("feasible_incumbent") or task_status.get("incumbent_found"))
            if feasible and task_status.get("status") in {"failed", "timed_out", "interrupted"}:
                warnings.append(f"任务 {task_id} 未完成精确求解，但记录了可行 incumbent；进入警告验收")
            else:
                failures.append(f"任务 {task_id} 不是 succeeded，且没有可行 incumbent")
        for name in ("status.json", "task.json"):
            if not (TASK_ROOT / task_id / name).exists():
                failures.append(f"任务缺少 {name}")
        for field in ("stdout", "stderr"):
            log_path = task_status.get(field)
            if not log_path or not resolve_project_path(log_path).is_file():
                failures.append(f"任务当前 attempt 缺少 {field} 日志")

    candidates = [path for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in {".csv", ".json", ".npy", ".npz"} and path.name not in {"machine_sanity.json", "archive_manifest.json"}]
    numeric = [inspect_numeric_file(path) for path in candidates]
    for item in numeric:
        if not item.get("finite", False):
            failures.append(f"数值文件存在非有限值或无法读取：{item['path']}")
    if not numeric:
        warnings.append("未发现 CSV/JSON/NPY/NPZ 数值结果，L2 无法自动检查")
    warnings.append("L3 量纲与公式、L4 常识与文献、L5 跨小问一致性和条件性 L6 实验须由 sanity-checker 审查")
    automated_status = "NEEDS_REVISION" if failures else "PASS_WITH_WARNING"
    return {
        "checked_at": utc_now(),
        "directory": relative(directory),
        "task_id": task_id,
        "task_status": task_status.get("status") if task_status else None,
        "automated_scope": ["L1", "L2-finite"],
        "automated_status": automated_status,
        "failures": failures,
        "warnings": warnings,
        "quality_status": "needs_revision" if failures else "degraded_review" if warnings else "pass",
        "numeric_files": numeric,
        "manual_levels_pending": ["L2-model-constraints", "L3", "L4", "L5", "L6-conditional"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="AutoMM 通用 sanity 检查")
    parser.add_argument("--question-dir", required=True)
    parser.add_argument("--task-id")
    parser.add_argument("--output")
    args = parser.parse_args()
    directory = resolve_project_path(args.question_dir, must_exist=True)
    if not directory.is_dir():
        raise SystemExit("question-dir 必须是项目内目录")
    payload = build_report(directory, args.task_id)
    output = resolve_project_path(args.output) if args.output else directory / "machine_sanity.json"
    write_json(output, payload)
    report = directory / "sanity_report.md"
    report_text = f"""# Sanity Check Report

- 自动检查状态：{payload['automated_status']}
- 检查时间：{payload['checked_at']}
- 任务 ID：{args.task_id or '未指定'}

## Level 1：文件和运行完整性

{chr(10).join(f'- {item}' for item in payload['failures']) or '- 自动检查未发现阻断项'}

## Level 2：数值范围和有限性

- 已检查 {len(payload['numeric_files'])} 个数值文件。
- 模型特有范围和约束仍需 Agent 检查。

## 后续人工语义检查

- L3 量纲与公式；L4 常识与文献合理性；L5 跨小问一致性；L6 按题目决定是否进行稳健性或消融实验。

## 路由

- failures：{len(payload['failures'])}
- warnings：{len(payload['warnings'])}
- 机器报告：{relative(output)}
"""
    write_text(report, report_text)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(2 if payload["failures"] else 0)


if __name__ == "__main__":
    main()
