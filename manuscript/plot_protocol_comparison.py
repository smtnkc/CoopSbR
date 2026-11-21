"""Render the manuscript-width GPU protocol comparison from the archived measurements."""

import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import MultipleLocator


MANUSCRIPT = Path(__file__).resolve().parent
REPORT = MANUSCRIPT.parent / "reports" / "fused-update-main-20261120"
SUPPLEMENT = MANUSCRIPT.parent / "reports" / "ucsc-anchors-20261121"
INK = "#2C3E50"
# Match Figure 3's printed type sizes. The 7.15-inch source for that figure
# spans the text width, while this 5-inch source spans 63% of that width.
TYPE_SCALE = 5 / (0.63 * 7.15)
STYLE = {
    "font.family": "Helvetica",
    "font.size": 9 * TYPE_SCALE,
    "axes.titlesize": 9 * TYPE_SCALE,
    "axes.titleweight": "bold",
    "axes.titlecolor": INK,
    "axes.labelsize": 9 * TYPE_SCALE,
    "axes.labelcolor": INK,
    "xtick.labelsize": 8 * TYPE_SCALE,
    "ytick.labelsize": 8 * TYPE_SCALE,
    "xtick.labelcolor": INK,
    "ytick.labelcolor": INK,
    "legend.fontsize": 8.5,
    "pdf.use14corefonts": True,
}
GRAY = "#7F8C8D"
# Gold, rust, and slate teal from the reference observer-discrepancy dot plot.
METHODS = [
    ("baseline", "Graph / four barriers", "Cooperative (4 barriers)", "#dab365", "o"),
    ("full", "Graph / full copy", "Fused full copy (3 barriers)", "#a3573f", "^"),
    ("changed", "Graph / changed intervals", "Fused changed intervals (3 barriers)", "#4b7179", "D"),
]
ROW_COLORS = ("#ffffff", "#eeeeee")


def read_csv(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def style_axis(ax, grid_axis):
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(INK)
    ax.spines[["left", "bottom"]].set_linewidth(0.8)
    ax.tick_params(color=INK, length=3, width=0.75, pad=3)
    ax.grid(axis=grid_axis, color=GRAY, linestyle=":", linewidth=0.6, alpha=0.50)
    ax.set_axisbelow(True)


def draw_case_panel(ax, rows, labels, title, graph_style):
    style_axis(ax, "x")
    for index in range(len(rows)):
        ax.axhspan(index - 0.5, index + 0.5, color=ROW_COLORS[index % 2],
                   linewidth=0, zorder=0)
    ax.axvline(1, zorder=2, **graph_style)
    panel_ratios = []
    for method_index, (method, _, _, color, marker) in enumerate(METHODS):
        ratios = [
            float(row["graph_end_to_end_ms"]) / float(row[f"{method}_end_to_end_ms"])
            for row in rows
        ]
        panel_ratios.extend(ratios)
        offsets = [i + (method_index - 1) * 0.27 for i in range(len(rows))]
        ax.scatter(ratios, offsets, s=21, color=color, marker=marker,
                   edgecolor=INK, linewidth=0.45, zorder=3)
    ax.set_yticks(range(len(rows)), labels)
    ax.set_ylim(len(rows) - 0.5, -0.5)
    ax.xaxis.set_major_locator(MultipleLocator(0.2))
    ax.set_title(title, loc="left", x=-0.10, pad=6)
    return panel_ratios


def draw(report, output, supplement=SUPPLEMENT):
    comparisons = {comparison for _, comparison, _, _, _ in METHODS}
    cells = [
        row for row in read_csv(report / "paired-cells.csv")
        if row["metric"] == "end_to_end_ms" and row["comparison"] in comparisons
    ]
    real = sorted(
        (row for row in read_csv(report / "pairs.csv") if row["family"] == "real"),
        key=lambda row: row["case_id"],
    )

    fly_labels = []
    for row in real:
        _, species, arm = row["case_id"].rsplit("-", maxsplit=2)
        fly_labels.append(f"{species} · {arm}")
    anchor_pairs = {row["case_id"]: row for row in read_csv(supplement / "pairs.csv")}
    anchor_cases = json.loads((supplement / "manifest.json").read_text())["cases"]
    anchors = [anchor_pairs[case["id"]] for case in anchor_cases]
    anchor_labels = [f"{case['chromosome']} · {case['min_block_bp']}" for case in anchor_cases]

    with plt.rc_context(STYLE):
        # Keep the 5-inch source canvas used by the manuscript.
        fig = plt.figure(figsize=(5, 4.95))
        top = fig.add_gridspec(
            1, 2, left=0.138, right=0.982, bottom=0.542, top=0.865, wspace=0.145
        )
        left = fig.add_subplot(top[0])
        right = fig.add_subplot(top[1], sharex=left, sharey=left)
        lower = fig.add_gridspec(
            1, 2, left=0.138, right=0.982, bottom=0.087, top=0.415, wspace=0.46
        )
        fly_ax = fig.add_subplot(lower[0])
        anchor_ax = fig.add_subplot(lower[1], sharex=fly_ax)

        graph_style = dict(color=GRAY, linestyle=(0, (4, 2)), linewidth=1)
        graph_handle = Line2D([], [], label="CUDA Graph (reference)", **graph_style)
        legend_handles = [graph_handle]
        lowest = min(float(row["ci95_low"]) for row in cells)
        highest = max(float(row["ci95_high"]) for row in cells)
        for ax, family, title in (
            (left, "uniform", "(a) Uniform permutations"),
            (right, "semi", "(b) Semi-random (k = 64)"),
        ):
            style_axis(ax, "y")
            ax.axhline(1, zorder=2, **graph_style)
            for _, comparison, label, color, marker in METHODS:
                rows = sorted(
                    (row for row in cells
                     if row["family"] == family and row["comparison"] == comparison),
                    key=lambda row: int(row["n"]),
                )
                lengths = [int(row["n"]) for row in rows]
                ratios = [float(row["median_ratio"]) for row in rows]
                errors = [
                    [ratio - float(row["ci95_low"]) for ratio, row in zip(ratios, rows)],
                    [float(row["ci95_high"]) - ratio for ratio, row in zip(ratios, rows)],
                ]
                line, _, _ = ax.errorbar(
                    lengths, ratios, yerr=errors, color=color, marker=marker,
                    markersize=4.5, markeredgecolor=INK, markeredgewidth=0.45,
                    linewidth=1.1, elinewidth=0.75, capsize=1.6, zorder=3,
                )
                if ax is left:
                    line.set_label(label)
                    legend_handles.append(line)
            ax.set_title(title, loc="left", pad=6)
            ax.set_xscale("log", base=2)
            ax.set_xticks(lengths, [str(n // 1024) for n in lengths])
            ax.set_xlim(lengths[0] / 1.27, lengths[-1] * 1.27)
            ax.set_ylim(min(0.95, lowest - 0.04), max(1.87, highest + 0.045))
            ax.yaxis.set_major_locator(MultipleLocator(0.2))

        left.set_ylabel("End-to-end speedup vs. Graph", color=INK)
        right.tick_params(axis="y", labelleft=False)
        fig.text(0.56, 0.48, "Permutation length (×1,024 markers)", ha="center", color=INK)

        fly_ratios = draw_case_panel(
            fly_ax, real, fly_labels, "(c) Drosophila gene orders", graph_style
        )
        anchor_ratios = draw_case_panel(
            anchor_ax, anchors, anchor_labels, "(d) Human–chimp blocks", graph_style
        )
        ratios = fly_ratios + anchor_ratios
        fly_ax.set_xlim(min(0.95, min(ratios) - 0.04), max(1.84, max(ratios) + 0.04))
        fig.text(0.56, 0.024, "End-to-end speedup vs. Graph", ha="center", color=INK)
        fig.legend(
            handles=[legend_handles[i] for i in (0, 2, 1, 3)],
            loc="upper center", bbox_to_anchor=(0.5, 0.999), ncol=2,
            frameon=False, handlelength=2.4, columnspacing=2.0,
        )
        fig.savefig(output)
        plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=REPORT)
    parser.add_argument("--supplement-dir", type=Path, default=SUPPLEMENT)
    parser.add_argument("--output", type=Path, default=MANUSCRIPT / "gpu-protocol-comparison.pdf")
    args = parser.parse_args()
    draw(args.report_dir, args.output, args.supplement_dir)
