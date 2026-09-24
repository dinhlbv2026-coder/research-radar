"""Biểu đồ cho báo cáo Research Radar (matplotlib, PNG).

Quy ước (theo bộ nguyên tắc dataviz đã kiểm định):
- Màu theo CHỦ ĐỀ, cố định thứ tự, không xoay vòng; bảng 4 màu đã qua kiểm tra mù màu (CVD ΔE ≥ 9).
- Một trục duy nhất; so sánh tốc độ tăng các từ khoá khác quy mô bằng thang log (không dùng trục kép).
- Nhãn giá trị/nhãn tên đặt trực tiếp trên hình (bù cho 2 màu có tương phản < 3:1).
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e6e5e1"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]

plt.rcParams.update({
    "font.family": "DejaVu Sans",  # có đủ dấu tiếng Việt
    "font.size": 10,
    "axes.edgecolor": GRID,
    "axes.labelcolor": INK2,
    "xtick.color": INK2,
    "ytick.color": INK2,
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
})


def _clean(ax):
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)


def hot_ranking(rows: list[dict], out: Path, title: str) -> Path:
    """Thanh ngang: CAGR chuẩn hoá của mọi từ khoá, màu theo chủ đề.
    rows: [{"topic": str, "topic_idx": int, "query": str, "rel": float}]"""
    rows = sorted([r for r in rows if r["rel"] is not None], key=lambda r: r["rel"])
    if not rows:
        return out
    h = 0.42 * len(rows) + 1.6
    fig, ax = plt.subplots(figsize=(9, h), dpi=150)
    ys = range(len(rows))
    vals = [r["rel"] * 100 for r in rows]
    colors = [SERIES[r["topic_idx"] % len(SERIES)] for r in rows]
    ax.barh(list(ys), vals, color=colors, height=0.62, edgecolor=SURFACE, linewidth=2)
    ax.axvline(0, color=INK2, linewidth=1)
    span = max(abs(v) for v in vals) or 1
    for y, v in zip(ys, vals):
        lab = "0%" if round(v) == 0 else f"{v:+.0f}%"
        ax.text(v + (0.015 * span if v >= 0 else -0.015 * span), y, lab,
                va="center", ha="left" if v >= 0 else "right", color=INK, fontsize=9)
    ax.set_yticks(list(ys))
    ax.set_yticklabels([r["query"].replace('"', "") for r in rows], color=INK, fontsize=9)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_xlim(min(0, min(vals)) - 0.18 * span, max(0, max(vals)) + 0.18 * span)
    ax.set_xlabel("Tăng nhanh hơn (+) / chậm hơn (−) mặt bằng công bố chung, %/năm")
    _clean(ax)
    seen, handles = {}, []
    for r in rows:
        if r["topic"] not in seen:
            seen[r["topic"]] = r["topic_idx"]
    for name, idx in sorted(seen.items(), key=lambda kv: kv[1]):
        handles.append(plt.Rectangle((0, 0), 1, 1, color=SERIES[idx % len(SERIES)], label=name))
    ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2,
              frameon=False, fontsize=9, labelcolor=INK)
    fig.suptitle(title, x=0.01, ha="left", fontsize=13, fontweight="bold", color=INK, y=0.995)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def topic_trend(growth: list[dict], out: Path, title: str, current_year: int, color_idx: int = 0) -> Path:
    """Đường số công bố theo năm của các từ khoá một chủ đề (thang log, một trục).
    Cả chủ đề dùng CÙNG màu của chủ đề đó (khớp bản đồ độ nóng); từ khoá phân biệt bằng
    kiểu điểm + nhãn trực tiếp. Năm hiện tại chưa trọn → nét đứt, điểm rỗng."""
    import math

    from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter

    growth = [g for g in growth if any(g["series"].values())]
    if not growth:
        return out
    c = SERIES[color_idx % len(SERIES)]
    markers = ["o", "s", "^", "D"]
    glyphs = ["●", "■", "▲", "◆"]  # nhãn mang cùng ký hiệu điểm → nhận diện được khi các đường cắt nhau
    fig, ax = plt.subplots(figsize=(9, 4.2), dpi=150)
    ends = []
    for i, g in enumerate(growth):
        m = markers[i % len(markers)]
        lw = 2.6 if i == 0 else 1.8
        yrs = [int(y) for y in g["series"]]
        vals = [max(v, 0.8) for v in g["series"].values()]  # log không nhận 0
        full = [(y, v) for y, v in zip(yrs, vals) if y < current_year]
        part = [(y, v) for y, v in zip(yrs, vals) if y >= current_year - 1]
        ax.plot([p[0] for p in full], [p[1] for p in full], color=c, linewidth=lw, marker=m,
                markersize=6, markeredgecolor=SURFACE, markeredgewidth=1.5)
        end = full[-1]
        if len(part) == 2:
            ax.plot([p[0] for p in part], [p[1] for p in part], color=c, linewidth=lw, linestyle=(0, (3, 2)))
            ax.plot(part[1][0], part[1][1], marker=m, markersize=7, markerfacecolor=SURFACE,
                    markeredgecolor=c, markeredgewidth=2)
            end = part[1]
        ends.append([math.log10(end[1]), f"{glyphs[i % len(glyphs)]} " + g["query"].replace('"', ""), end[0]])
    ax.set_yscale("log")
    lo, hi = ax.get_ylim()
    gap = 0.075 * (math.log10(hi) - math.log10(lo))
    ends.sort()
    for k in range(1, len(ends)):  # giãn nhãn để không chồng nhau
        if ends[k][0] - ends[k - 1][0] < gap:
            ends[k][0] = ends[k - 1][0] + gap
    for ly, label, x in ends:
        ax.text(x + 0.25, 10 ** ly, label, va="center", fontsize=8.5, color=INK)
    ax.yaxis.set_major_locator(LogLocator(base=10))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}".replace(",", ".")))
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.tick_params(which="minor", length=0)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8, which="major")
    ax.set_axisbelow(True)
    ax.set_ylabel("Số công bố (thang log)")
    yrs_all = sorted({int(y) for g in growth for y in g["series"]})
    ax.set_xticks(yrs_all)
    ax.set_xlim(yrs_all[0] - 0.3, yrs_all[-1] + 3.2)
    _clean(ax)
    ax.text(0, -0.16, f"Nét đứt, điểm rỗng: năm {current_year} chưa trọn. Nguồn: OpenAlex (tiêu đề + tóm tắt).",
            transform=ax.transAxes, fontsize=8, color=INK2)
    fig.suptitle(title, x=0.01, ha="left", fontsize=12, fontweight="bold", color=INK)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def news_sources(counts: list[tuple[str, int]], out: Path, title: str) -> Path:
    """Thanh ngang một màu: các nguồn tin xuất hiện nhiều nhất trong tuần."""
    counts = counts[:10][::-1]
    if not counts:
        return out
    fig, ax = plt.subplots(figsize=(9, 0.38 * len(counts) + 1.2), dpi=150)
    ys = range(len(counts))
    ax.barh(list(ys), [c for _, c in counts], color=SERIES[0], height=0.6, edgecolor=SURFACE, linewidth=2)
    for y, (_, c) in zip(ys, counts):
        ax.text(c + 0.1, y, str(c), va="center", fontsize=9, color=INK)
    ax.set_yticks(list(ys))
    ax.set_yticklabels([n for n, _ in counts], color=INK, fontsize=9)
    ax.xaxis.set_visible(False)
    _clean(ax)
    ax.spines["bottom"].set_visible(False)
    fig.suptitle(title, x=0.01, ha="left", fontsize=12, fontweight="bold", color=INK)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out
