#!/usr/bin/env python3
"""Offline 2D wavelet experiment on concept short-heat Top200 plane.

Does not touch the web app. Writes PNGs under experiments/out/.

Usage (from repo root):
  .venv/bin/python scripts/concept_top_wavelet2d_offline.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pywt
from matplotlib import font_manager

from app.db import (
    fetch_concept_heat_named_window,
    fetch_heat_dates_ending,
    fetch_rotation_dates,
)
from app.themes.concept_wave import CONCEPT_TOP_N, build_concept_top_heat_payload

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "experiments" / "out"
WINDOW_DAYS = 60
WAVELET = "db4"
LEVEL = 3
DWT_MODE = "symmetric"


def _setup_font() -> None:
    candidates = [
        "PingFang SC",
        "Heiti SC",
        "STHeiti",
        "Noto Sans CJK SC",
        "Arial Unicode MS",
        "Songti SC",
    ]
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            return
    plt.rcParams["axes.unicode_minus"] = False


def _load_top_grid() -> tuple[np.ndarray, list[str], list[str], str]:
    slider = fetch_rotation_dates("concept", 10)
    if not slider:
        raise RuntimeError("no concept rotation dates")
    selected = slider[-1]
    window = fetch_heat_dates_ending("concept", selected, WINDOW_DAYS)
    if not window:
        raise RuntimeError("empty heat window")
    rows = fetch_concept_heat_named_window(window[0], window[-1])
    payload = build_concept_top_heat_payload(
        window_dates=window,
        heat_rows=rows,
        top_n=CONCEPT_TOP_N,
    )
    if payload.get("empty_message"):
        raise RuntimeError(payload["empty_message"])
    z = np.asarray(payload["z_short"], dtype=float)
    # z shape: (T dates, N concepts)
    dates = list(payload["dates"])
    names = list(payload["board_names"])
    as_of = str(payload["as_of"])
    return z, dates, names, as_of


def _date_ticks(dates: list[str], n: int = 6) -> tuple[list[int], list[str]]:
    if not dates:
        return [], []
    idx = np.linspace(0, len(dates) - 1, num=min(n, len(dates)), dtype=int)
    return idx.tolist(), [dates[i][5:] for i in idx]  # MM-DD


def _concept_ticks(names: list[str], n: int = 8) -> tuple[list[int], list[str]]:
    if not names:
        return [], []
    idx = np.linspace(0, len(names) - 1, num=min(n, len(names)), dtype=int)
    labels = []
    for i in idx:
        label = names[i]
        labels.append(label if len(label) <= 6 else label[:5] + "…")
    return idx.tolist(), labels


def _imshow_heat(ax, grid: np.ndarray, dates: list[str], names: list[str], title: str):
    im = ax.imshow(
        grid,
        aspect="auto",
        origin="lower",
        interpolation="nearest",
        cmap="YlOrRd",
        vmin=0.0,
        vmax=1.0,
    )
    ax.set_title(title, fontsize=11)
    ax.set_xlabel("概念叶序（共动近 → 相邻）")
    ax.set_ylabel("交易日")
    xt, xl = _concept_ticks(names)
    yt, yl = _date_ticks(dates)
    ax.set_xticks(xt)
    ax.set_xticklabels(xl, rotation=35, ha="right", fontsize=8)
    ax.set_yticks(yt)
    ax.set_yticklabels(yl, fontsize=8)
    return im


def _pad_to_even(arr: np.ndarray) -> np.ndarray:
    """Pad so both axes divisible by 2**LEVEL for clean wavedec2."""
    t, n = arr.shape
    need_t = (2**LEVEL - (t % (2**LEVEL))) % (2**LEVEL)
    need_n = (2**LEVEL - (n % (2**LEVEL))) % (2**LEVEL)
    if need_t == 0 and need_n == 0:
        return arr
    return np.pad(arr, ((0, need_t), (0, need_n)), mode="edge")


def _energy(arr: np.ndarray) -> float:
    return float(np.sum(np.square(arr)))


def _detail_band_maps(
    coeffs: list,
) -> dict[str, np.ndarray]:
    """Rebuild single-band images (others zeroed) at reconstructed size."""
    cA = coeffs[0]
    details = coeffs[1:]
    bands: dict[str, np.ndarray] = {}

    zero_details = [
        tuple(np.zeros_like(band) for band in level) for level in details
    ]
    bands["A3 粗结构（主线背景）"] = pywt.waverec2(
        [cA, *zero_details], WAVELET, mode=DWT_MODE
    )

    for level_i, level in enumerate(details):
        label_scale = level_i + 1
        name = {
            1: f"D{LEVEL} 中粗（团块/二周量级）",
            2: f"D{LEVEL - 1} 中细",
            3: "D1 细尺度（脉冲）",
        }.get(label_scale, f"D{label_scale}")
        recon_details = []
        for j, other in enumerate(details):
            if j == level_i:
                recon_details.append(other)
            else:
                recon_details.append(tuple(np.zeros_like(b) for b in other))
        bands[name] = pywt.waverec2(
            [np.zeros_like(cA), *recon_details], WAVELET, mode=DWT_MODE
        )

    cH1, cV1, cD1 = details[-1]
    zeros_rest = [
        tuple(np.zeros_like(b) for b in level) for level in details[:-1]
    ]
    bands["细·水平(时间向起伏)"] = pywt.waverec2(
        [
            np.zeros_like(cA),
            *zeros_rest,
            (cH1, np.zeros_like(cV1), np.zeros_like(cD1)),
        ],
        WAVELET,
        mode=DWT_MODE,
    )
    bands["细·垂直(叶序向团块边界)"] = pywt.waverec2(
        [
            np.zeros_like(cA),
            *zeros_rest,
            (np.zeros_like(cH1), cV1, np.zeros_like(cD1)),
        ],
        WAVELET,
        mode=DWT_MODE,
    )
    bands["细·对角(斜向迁移感)"] = pywt.waverec2(
        [
            np.zeros_like(cA),
            *zeros_rest,
            (np.zeros_like(cH1), np.zeros_like(cV1), cD1),
        ],
        WAVELET,
        mode=DWT_MODE,
    )
    return bands


def _crop_like(arr: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    t, n = shape
    return arr[:t, :n]


def main() -> None:
    _setup_font()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    z, dates, names, as_of = _load_top_grid()
    t0, n0 = z.shape
    print(f"loaded Top{n0} grid {z.shape} as_of={as_of}")

    # Center for wavelet (keep approximation readable)
    z_mean = float(np.mean(z))
    z_c = z - z_mean
    z_pad = _pad_to_even(z_c)
    coeffs = pywt.wavedec2(z_pad, WAVELET, level=LEVEL, mode=DWT_MODE)

    # --- Figure 1: original + approximation + multi-scale energy ---
    bands = _detail_band_maps(coeffs)
    approx = _crop_like(bands["A3 粗结构（主线背景）"], (t0, n0)) + z_mean
    fine = _crop_like(bands["D1 细尺度（脉冲）"], (t0, n0))
    mid = _crop_like(bands["D3 中粗（团块/二周量级）"], (t0, n0))

    fig1, axes = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)
    im0 = _imshow_heat(axes[0, 0], z, dates, names, f"原图 · Top{n0} 短热翻转 · {as_of}")
    fig1.colorbar(im0, ax=axes[0, 0], fraction=0.035, pad=0.02)
    im1 = _imshow_heat(
        axes[0, 1],
        np.clip(approx, 0, 1),
        dates,
        names,
        "A3 粗结构（+均值）≈ 主线/占位背景",
    )
    fig1.colorbar(im1, ax=axes[0, 1], fraction=0.035, pad=0.02)

    vmax_d = float(np.percentile(np.abs(np.concatenate([mid.ravel(), fine.ravel()])), 99))
    vmax_d = max(vmax_d, 1e-3)
    im2 = axes[1, 0].imshow(
        mid,
        aspect="auto",
        origin="lower",
        cmap="RdBu_r",
        vmin=-vmax_d,
        vmax=vmax_d,
        interpolation="nearest",
    )
    axes[1, 0].set_title("D3 中粗细节 · 红=该尺度偏热 / 蓝=偏冷")
    axes[1, 0].set_xlabel("概念叶序")
    axes[1, 0].set_ylabel("交易日")
    yt, yl = _date_ticks(dates)
    xt, xl = _concept_ticks(names)
    axes[1, 0].set_yticks(yt)
    axes[1, 0].set_yticklabels(yl, fontsize=8)
    axes[1, 0].set_xticks(xt)
    axes[1, 0].set_xticklabels(xl, rotation=35, ha="right", fontsize=8)
    fig1.colorbar(im2, ax=axes[1, 0], fraction=0.035, pad=0.02)

    im3 = axes[1, 1].imshow(
        fine,
        aspect="auto",
        origin="lower",
        cmap="RdBu_r",
        vmin=-vmax_d,
        vmax=vmax_d,
        interpolation="nearest",
    )
    axes[1, 1].set_title("D1 细尺度 · 局部脉冲 / 尖峰")
    axes[1, 1].set_xlabel("概念叶序")
    axes[1, 1].set_ylabel("交易日")
    axes[1, 1].set_yticks(yt)
    axes[1, 1].set_yticklabels(yl, fontsize=8)
    axes[1, 1].set_xticks(xt)
    axes[1, 1].set_xticklabels(xl, rotation=35, ha="right", fontsize=8)
    fig1.colorbar(im3, ax=axes[1, 1], fraction=0.035, pad=0.02)

    path1 = OUT_DIR / f"concept_top_wavelet_multiscale_{as_of}.png"
    fig1.savefig(path1, dpi=140)
    plt.close(fig1)
    print("wrote", path1)

    # --- Figure 2: energy by scale + directional ---
    cA = coeffs[0]
    energies = [("A3 粗结构", _energy(cA))]
    dir_energies = {"水平cH": 0.0, "垂直cV": 0.0, "对角cD": 0.0}
    for level_i, (cH, cV, cD) in enumerate(coeffs[1:]):
        # level_i=0 coarsest detail
        tag = f"D{LEVEL - level_i}"
        energies.append((f"{tag} 合计", _energy(cH) + _energy(cV) + _energy(cD)))
        dir_energies["水平cH"] += _energy(cH)
        dir_energies["垂直cV"] += _energy(cV)
        dir_energies["对角cD"] += _energy(cD)

    total = sum(v for _, v in energies) or 1.0
    labels = [k for k, _ in energies]
    shares = [100.0 * v / total for _, v in energies]

    fig2, axes2 = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
    axes2[0].bar(labels, shares, color=["#b45309", "#ea580c", "#f59e0b", "#fbbf24"])
    axes2[0].set_ylabel("能量占比 %")
    axes2[0].set_title(f"多尺度能量分解 · Top{n0} · {as_of}")
    axes2[0].tick_params(axis="x", rotation=20)
    for i, s in enumerate(shares):
        axes2[0].text(i, s + 0.8, f"{s:.1f}%", ha="center", fontsize=9)

    dlabels = list(dir_energies.keys())
    dvals = list(dir_energies.values())
    dtotal = sum(dvals) or 1.0
    dshares = [100.0 * v / dtotal for v in dvals]
    axes2[1].bar(dlabels, dshares, color=["#1d4ed8", "#7c3aed", "#db2777"])
    axes2[1].set_ylabel("细节能量占比 %")
    axes2[1].set_title("方向拆分（全部细节层合计）")
    for i, s in enumerate(dshares):
        axes2[1].text(i, s + 0.8, f"{s:.1f}%", ha="center", fontsize=9)
    axes2[1].text(
        0.5,
        -0.22,
        "水平≈沿时间起伏 · 垂直≈叶序团块边界 · 对角≈斜向共动/迁移感",
        transform=axes2[1].transAxes,
        ha="center",
        fontsize=8,
        color="#57534e",
    )

    path2 = OUT_DIR / f"concept_top_wavelet_energy_{as_of}.png"
    fig2.savefig(path2, dpi=140)
    plt.close(fig2)
    print("wrote", path2)

    # --- Figure 3: directional fine bands ---
    fig3, axes3 = plt.subplots(1, 3, figsize=(15, 4.8), constrained_layout=True)
    dir_maps = [
        ("细·水平(时间向起伏)", "水平 · 时间向升降温"),
        ("细·垂直(叶序向团块边界)", "垂直 · 叶序团块边界"),
        ("细·对角(斜向迁移感)", "对角 · 斜向迁移感"),
    ]
    stacked = np.concatenate(
        [_crop_like(bands[k], (t0, n0)).ravel() for k, _ in dir_maps]
    )
    vmax = float(np.percentile(np.abs(stacked), 99))
    vmax = max(vmax, 1e-3)
    for ax, (key, title) in zip(axes3, dir_maps):
        g = _crop_like(bands[key], (t0, n0))
        im = ax.imshow(
            g,
            aspect="auto",
            origin="lower",
            cmap="RdBu_r",
            vmin=-vmax,
            vmax=vmax,
            interpolation="nearest",
        )
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("概念叶序")
        ax.set_ylabel("交易日")
        ax.set_yticks(yt)
        ax.set_yticklabels(yl, fontsize=7)
        ax.set_xticks(xt)
        ax.set_xticklabels(xl, rotation=35, ha="right", fontsize=7)
        fig3.colorbar(im, ax=ax, fraction=0.04, pad=0.02)

    path3 = OUT_DIR / f"concept_top_wavelet_directions_{as_of}.png"
    fig3.savefig(path3, dpi=140)
    plt.close(fig3)
    print("wrote", path3)

    # --- text summary ---
    summary = OUT_DIR / f"concept_top_wavelet_summary_{as_of}.txt"
    lines = [
        f"as_of={as_of}",
        f"grid=({t0} dates) x ({n0} concepts)",
        f"wavelet={WAVELET} level={LEVEL}",
        f"z_mean={z_mean:.4f}",
        "energy_share_pct:",
    ]
    for lab, share in zip(labels, shares):
        lines.append(f"  {lab}: {share:.2f}%")
    lines.append("direction_share_pct (all detail levels):")
    for lab, share in zip(dlabels, dshares):
        lines.append(f"  {lab}: {share:.2f}%")
    lines.append("")
    lines.append("读图提示:")
    lines.append("- A3 粗结构：像长红柱/主线占位背景；近端仍红=占位，近端变淡=占位回落。")
    lines.append("- D3 中粗：团块级两周量级起伏；红蓝交替可对应二波回补感。")
    lines.append("- D1 细尺度：孤立尖峰≈脉冲，勿当主线。")
    lines.append("- 垂直细节强：叶序上团块边界清晰；对角细节强：热度可能沿相邻概念斜向迁移。")
    lines.append("- 横轴是聚类叶序，不是产业链距离。")
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", summary)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
