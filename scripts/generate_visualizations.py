"""统一图表风格、生成基础图表并登记稳定 figure ID。"""

from __future__ import annotations

import argparse
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from automm.common import config_section, hash_path, relative, resolve_project_path
from automm.visualization import inspect_png, record_figure_review, register_figure, stable_figure_id
from matplotlib import font_manager


def style_config(problem_id: str | None = None, question_id: str | None = None) -> dict:
    return config_section("visualization", problem_id, question_id)


def select_font(config: dict) -> str:
    available = {font.name for font in font_manager.fontManager.ttflist}
    for candidate in [config.get("preferred_font"), *config.get("fallback_fonts", [])]:
        if candidate and candidate in available:
            return candidate
    return "DejaVu Sans"


def apply_style(config: dict) -> str:
    font = select_font(config)
    palette = config.get("palette", {})
    plt.rcParams.update(
        {
            "font.family": font,
            "font.size": config.get("font_size", 11),
            "axes.titlesize": config.get("title_size", 14),
            "axes.prop_cycle": plt.cycler(
                color=[
                    palette.get("primary", "#1F4E79"),
                    palette.get("secondary", "#70AD47"),
                    palette.get("accent", "#ED7D31"),
                    palette.get("neutral", "#7F8C8D"),
                ]
            ),
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": config.get("background", "white"),
            "savefig.facecolor": config.get("background", "white"),
        }
    )
    return font


def plot_csv(args: argparse.Namespace) -> dict:
    config = style_config(args.problem_id, args.question_id)
    font = apply_style(config)
    source = resolve_project_path(args.csv, must_exist=True)
    frame = pd.read_csv(source)
    columns = [name for name in [args.x, *args.y] if name]
    missing = [name for name in columns if name not in frame.columns]
    if missing:
        raise ValueError(f"CSV 缺少列：{', '.join(missing)}")
    figure_id = stable_figure_id(
        problem_id=args.problem_id,
        question_id=args.question_id,
        kind=args.slug or args.kind,
        title=args.title,
        source_hash=hash_path(source),
        x=args.x,
        y=args.y,
        style=config,
    )
    output_dir = resolve_project_path(args.output_directory)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{figure_id}.png"
    fig, ax = plt.subplots(figsize=(config.get("figure_width", 10), config.get("figure_height", 6)))
    if args.kind == "line":
        for column in args.y:
            ax.plot(frame[args.x], frame[column], label=column, linewidth=2)
    elif args.kind == "scatter":
        for column in args.y:
            ax.scatter(frame[args.x], frame[column], label=column, alpha=0.78)
    elif args.kind == "bar":
        width = 0.8 / len(args.y)
        positions = np.arange(len(frame))
        for index, column in enumerate(args.y):
            ax.bar(positions + index * width, frame[column], width=width, label=column)
        ax.set_xticks(positions + width * (len(args.y) - 1) / 2, frame[args.x].astype(str))
    elif args.kind == "heatmap":
        labels = args.y or list(frame.select_dtypes("number").columns)
        if not labels:
            raise ValueError("heatmap 至少需要一个数值列")
        matrix = frame[labels].corr().to_numpy()
        image = ax.imshow(matrix, cmap="viridis", aspect="auto")
        ax.set_xticks(range(len(labels)), labels, rotation=45, ha="right")
        ax.set_yticks(range(len(labels)), labels)
        fig.colorbar(image, ax=ax)
    ax.set_title(args.title)
    if args.kind != "heatmap":
        ax.set_xlabel(args.x)
        ax.grid(alpha=0.2)
        if args.y:
            ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(output, dpi=config.get("dpi", 180), format="png", bbox_inches="tight")
    plt.close(fig)
    quality = inspect_png(output, args.problem_id, args.question_id)
    item = {
        "stable_id": figure_id,
        "problem_id": args.problem_id,
        "question_id": args.question_id,
        "assumption_version": args.assumption_version,
        "title": args.title,
        "path": relative(output),
        "source_data": relative(source),
        "script": "scripts/generate_visualizations.py",
        "kind": args.kind,
        "font": font,
        "included_in_summary": True,
        "included_in_paper": False,
        "quality_report": relative(output.with_suffix(".quality.json")),
        "quality_status": quality["status"],
        "visual_review": {"status": "pending", "reason": ""},
    }
    register_figure(args.problem_id, item)
    return item


def main() -> None:
    parser = argparse.ArgumentParser(description="AutoMM 可视化入口")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("check-style")
    review = sub.add_parser("review")
    review.add_argument("--problem-id", required=True)
    review.add_argument("--stable-id", required=True)
    review.add_argument("--status", choices=("passed", "needs_revision"), required=True)
    review.add_argument("--reason", required=True)
    plot = sub.add_parser("plot-csv")
    plot.add_argument("--problem-id", required=True)
    plot.add_argument("--question-id", required=True)
    plot.add_argument("--assumption-version", required=True)
    plot.add_argument("--csv", required=True)
    plot.add_argument("--kind", choices=("line", "scatter", "bar", "heatmap"), required=True)
    plot.add_argument("--x")
    plot.add_argument("--y", nargs="*", default=[])
    plot.add_argument("--title", required=True)
    plot.add_argument("--slug")
    plot.add_argument("--output-directory", required=True)
    args = parser.parse_args()
    if args.action == "check-style":
        config = style_config()
        print(
            json.dumps(
                {"font": select_font(config), "formats": config.get("formats"), "config": "config/visualization.yaml"},
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if args.action == "review":
        print(
            json.dumps(
                record_figure_review(args.problem_id, args.stable_id, args.status, args.reason),
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if args.kind != "heatmap" and (not args.x or not args.y):
        raise SystemExit("line/scatter/bar 必须提供 --x 和至少一个 --y")
    print(json.dumps(plot_csv(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
