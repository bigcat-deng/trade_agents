"""Shared 2D wavelet analysis on a short-heat plane (dates × seriated boards)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pywt

WAVELET = "db4"
LEVEL = 3
DWT_MODE = "symmetric"
FEATURE_TOP_N = 10
LATE_FRAC = 5  # late window = max(5, T // 5)
EXTREMUM_DAYS = 3  # read-chart extrema: last ≤3 trading days (≠ structure late_n)
EXTREMUM_TOP_N = 3

# Hard structure flags for backtest filters (cross-section quantile thresholds).
STRUCTURE_FLAG_KEYS = (
    "a3_still_hot",
    "a3_fading",
    "d3_warming",
    "d3_cooling",
    "d1_pulse",
)
FLAG_OCCUPANCY_Q = 0.70
FLAG_FADE_Q = 0.70
FLAG_PULSE_Q = 0.80
FLAG_FADE_CAP_Q = 0.50  # still_hot requires fade at/below this quantile


def analyze_heat_wavelet2d(
    *,
    z_short: list[list[float | None]],
    dates: list[str],
    board_names: list[str],
    board_codes: list[str],
    as_of: str | None,
    axis_note: str,
    feature_top_n: int = FEATURE_TOP_N,
    select_from: str | None = None,
    select_to: str | None = None,
    top_n: int | None = None,
) -> dict[str, Any]:
    """Run db4 multilevel 2D wavelet + feature tables on a hotness grid."""
    z = np.asarray(z_short, dtype=float)
    if z.ndim != 2 or z.size == 0:
        return {
            "empty_message": "没有可分析的热度矩阵",
            "as_of": as_of,
            "dates": [],
            "board_names": [],
            "board_codes": [],
            "top_n": top_n,
        }

    t0, n0 = z.shape
    late_n = max(5, t0 // LATE_FRAC)
    early_n = max(5, t0 // 3)

    z_mean = float(np.mean(z))
    z_c = z - z_mean
    z_pad = _pad_to_power(z_c, LEVEL)
    coeffs = pywt.wavedec2(z_pad, WAVELET, level=LEVEL, mode=DWT_MODE)

    bands = _band_maps(coeffs, (t0, n0), z_mean)
    energy = _energy_shares(coeffs)
    directions = _direction_shares(coeffs)
    features = _entity_features(
        names=board_names,
        codes=board_codes,
        z=z,
        a3=bands["approx"],
        d3=bands["d3"],
        d1=bands["d1"],
        late_n=late_n,
        early_n=early_n,
        top_n=feature_top_n,
    )
    extremum_n = min(EXTREMUM_DAYS, t0)
    band_extrema = _band_extrema(
        names=board_names,
        codes=board_codes,
        dates=dates,
        z=z,
        a3=bands["approx"],
        d3=bands["d3"],
        d1=bands["d1"],
        extremum_n=extremum_n,
        top_n=EXTREMUM_TOP_N,
    )
    structure_flags = compute_structure_flags(
        names=board_names,
        codes=board_codes,
        z=z,
        a3=bands["approx"],
        d3=bands["d3"],
        d1=bands["d1"],
        late_n=late_n,
        as_of=as_of,
    )

    return {
        "empty_message": None,
        "as_of": as_of,
        "dates": list(dates),
        "board_names": list(board_names),
        "board_codes": list(board_codes),
        "top_n": top_n if top_n is not None else n0,
        "board_count": n0,
        "window_days": t0,
        "select_from": select_from,
        "select_to": select_to,
        "wavelet": WAVELET,
        "level": LEVEL,
        "z_mean": round(z_mean, 4),
        "late_days": late_n,
        "extremum_days": extremum_n,
        "z_short": z_short,
        "bands": {
            "approx": _tolist(bands["approx"]),
            "d3": _tolist(bands["d3"]),
            "d1": _tolist(bands["d1"]),
        },
        "energy": energy,
        "directions": directions,
        "features": features,
        "band_extrema": band_extrema,
        "structure_flags": structure_flags,
        "axis_note": axis_note,
    }


def compute_structure_flags(
    *,
    names: list[str],
    codes: list[str],
    z: np.ndarray,
    a3: np.ndarray,
    d3: np.ndarray,
    d1: np.ndarray,
    late_n: int,
    as_of: str | None = None,
    occupancy_q: float = FLAG_OCCUPANCY_Q,
    fade_q: float = FLAG_FADE_Q,
    pulse_q: float = FLAG_PULSE_Q,
    fade_cap_q: float = FLAG_FADE_CAP_Q,
) -> list[dict[str, Any]]:
    """Per-board binary structure flags for the window's last day (`as_of`).

    Thresholds are cross-sectional quantiles on that roster (same plane as the page).
    These are hard events for later cross ∩ filter backtests — not LLM prose.
    """
    del z  # reserved for future z-based flags
    t0 = int(a3.shape[0])
    if t0 < 2 or a3.shape[1] == 0:
        return []
    late = max(1, min(late_n, t0))
    mid = slice(t0 // 3, 2 * t0 // 3)

    a3_mean = a3.mean(axis=0)
    a3_late = a3[-late:].mean(axis=0)
    fade = a3_mean - a3_late
    occupancy = 0.5 * a3_mean + 0.5 * a3_late
    d3_mid = d3[mid].mean(axis=0) if mid.stop > mid.start else d3.mean(axis=0)
    d3_late = d3[-late:].mean(axis=0)
    d1_energy = (d1**2).mean(axis=0)
    pulse = d1_energy / (a3_mean + 0.15)

    occ_cut = float(np.quantile(occupancy, occupancy_q))
    fade_cut = float(np.quantile(fade, fade_q))
    fade_cap = float(np.quantile(fade, fade_cap_q))
    pulse_cut = float(np.quantile(pulse, pulse_q))

    rows: list[dict[str, Any]] = []
    for i, code in enumerate(codes):
        a3_still_hot = bool(occupancy[i] >= occ_cut and fade[i] <= fade_cap)
        a3_fading = bool(fade[i] >= fade_cut)
        d3_warming = bool(d3_mid[i] < 0.0 and d3_late[i] > 0.0)
        d3_cooling = bool(d3_mid[i] > 0.0 and d3_late[i] < 0.0)
        d1_pulse = bool(pulse[i] >= pulse_cut)
        rows.append(
            {
                "as_of": as_of,
                "board_code": code,
                "board_name": names[i] if i < len(names) else code,
                "a3_still_hot": a3_still_hot,
                "a3_fading": a3_fading,
                "d3_warming": d3_warming,
                "d3_cooling": d3_cooling,
                "d1_pulse": d1_pulse,
                "occupancy": round(float(occupancy[i]), 4),
                "fade": round(float(fade[i]), 4),
                "a3_late": round(float(a3_late[i]), 4),
                "d3_late": round(float(d3_late[i]), 4),
                "pulse": round(float(pulse[i]), 4),
            }
        )
    return rows


def _pad_to_power(arr: np.ndarray, level: int) -> np.ndarray:
    t, n = arr.shape
    step = 2**level
    need_t = (step - (t % step)) % step
    need_n = (step - (n % step)) % step
    if need_t == 0 and need_n == 0:
        return arr
    return np.pad(arr, ((0, need_t), (0, need_n)), mode="edge")


def _energy(arr: np.ndarray) -> float:
    return float(np.sum(np.square(arr)))


def _tolist(arr: np.ndarray) -> list[list[float]]:
    return [[float(v) for v in row] for row in arr]


def _crop(arr: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    t, n = shape
    return np.asarray(arr[:t, :n], dtype=float)


def _band_maps(
    coeffs: list,
    shape: tuple[int, int],
    z_mean: float,
) -> dict[str, np.ndarray]:
    c_a = coeffs[0]
    details = coeffs[1:]
    zero_details = [
        tuple(np.zeros_like(band) for band in level) for level in details
    ]
    approx = _crop(
        pywt.waverec2([c_a, *zero_details], WAVELET, mode=DWT_MODE),
        shape,
    ) + z_mean

    d_bands: list[np.ndarray] = []
    for level_i, _level in enumerate(details):
        recon_details = []
        for j, other in enumerate(details):
            if j == level_i:
                recon_details.append(other)
            else:
                recon_details.append(tuple(np.zeros_like(b) for b in other))
        d_bands.append(
            _crop(
                pywt.waverec2(
                    [np.zeros_like(c_a), *recon_details],
                    WAVELET,
                    mode=DWT_MODE,
                ),
                shape,
            )
        )
    return {
        "approx": approx,
        "d3": d_bands[0],
        "d1": d_bands[-1],
    }


def _energy_shares(coeffs: list) -> list[dict[str, float | str]]:
    c_a = coeffs[0]
    items: list[tuple[str, float]] = [("A3 粗结构", _energy(c_a))]
    for level_i, (c_h, c_v, c_d) in enumerate(coeffs[1:]):
        tag = f"D{LEVEL - level_i}"
        items.append((f"{tag} 合计", _energy(c_h) + _energy(c_v) + _energy(c_d)))
    total = sum(v for _, v in items) or 1.0
    return [
        {"label": label, "share_pct": round(100.0 * value / total, 2)}
        for label, value in items
    ]


def _direction_shares(coeffs: list) -> list[dict[str, float | str]]:
    h = v = d = 0.0
    for c_h, c_v, c_d in coeffs[1:]:
        h += _energy(c_h)
        v += _energy(c_v)
        d += _energy(c_d)
    total = h + v + d or 1.0
    return [
        {
            "label": "水平 cH（时间向）",
            "share_pct": round(100.0 * h / total, 2),
        },
        {
            "label": "垂直 cV（叶序向）",
            "share_pct": round(100.0 * v / total, 2),
        },
        {
            "label": "对角 cD（斜向）",
            "share_pct": round(100.0 * d / total, 2),
        },
    ]


def _top_rows(
    names: list[str],
    codes: list[str],
    scores: np.ndarray,
    *,
    a3_mean: np.ndarray,
    a3_late: np.ndarray,
    z_late: np.ndarray,
    d3_energy: np.ndarray,
    d1_energy: np.ndarray,
    top_n: int,
) -> list[dict[str, float | str]]:
    order = np.argsort(scores)[::-1][:top_n]
    rows: list[dict[str, float | str]] = []
    for idx in order:
        i = int(idx)
        rows.append(
            {
                "board_code": codes[i],
                "board_name": names[i],
                "score": round(float(scores[i]), 4),
                "a3_mean": round(float(a3_mean[i]), 3),
                "a3_late": round(float(a3_late[i]), 3),
                "z_late": round(float(z_late[i]), 3),
                "d3_energy": round(float(d3_energy[i]), 4),
                "d1_energy": round(float(d1_energy[i]), 4),
            }
        )
    return rows


def _entity_features(
    *,
    names: list[str],
    codes: list[str],
    z: np.ndarray,
    a3: np.ndarray,
    d3: np.ndarray,
    d1: np.ndarray,
    late_n: int,
    early_n: int,
    top_n: int,
) -> dict[str, list[dict[str, float | str]]]:
    del early_n  # reserved for future early-window contrasts
    t0 = z.shape[0]
    mid = slice(t0 // 3, 2 * t0 // 3)
    a3_mean = a3.mean(axis=0)
    a3_late = a3[-late_n:].mean(axis=0)
    z_late = z[-late_n:].mean(axis=0)
    d3_energy = (d3**2).mean(axis=0)
    d1_energy = (d1**2).mean(axis=0)

    occupancy = 0.5 * a3_mean + 0.5 * a3_late
    fade = a3_mean - a3_late
    d3_mid = d3[mid].mean(axis=0)
    d3_late = d3[-late_n:].mean(axis=0)
    rewarm = np.maximum(0.0, -d3_mid) * np.maximum(0.0, d3_late)
    pulse = d1_energy / (a3_mean + 0.15)

    common = dict(
        names=names,
        codes=codes,
        a3_mean=a3_mean,
        a3_late=a3_late,
        z_late=z_late,
        d3_energy=d3_energy,
        d1_energy=d1_energy,
        top_n=top_n,
    )
    return {
        "occupancy": _top_rows(scores=occupancy, **common),
        "fade": _top_rows(scores=fade, **common),
        "rewarm": _top_rows(scores=rewarm, **common),
        "mid_active": _top_rows(scores=d3_energy, **common),
        "pulse": _top_rows(scores=pulse, **common),
    }


def _extremum_side_rows(
    *,
    names: list[str],
    codes: list[str],
    scores: np.ndarray,
    indices: np.ndarray,
    side: str,
    digits: int,
) -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    for idx in indices:
        i = int(idx)
        rows.append(
            {
                "side": side,
                "board_code": codes[i],
                "board_name": names[i],
                "value": round(float(scores[i]), digits),
            }
        )
    return rows


def _band_extrema(
    *,
    names: list[str],
    codes: list[str],
    dates: list[str],
    z: np.ndarray,
    a3: np.ndarray,
    d3: np.ndarray,
    d1: np.ndarray,
    extremum_n: int,
    top_n: int,
) -> list[dict[str, Any]]:
    """Per-panel high/low boards from last ≤extremum_n days (≠ structure late_n)."""
    n_boards = z.shape[1]
    k = min(top_n, n_boards)
    date_from = dates[-extremum_n] if dates else None
    date_to = dates[-1] if dates else None

    panels = [
        {
            "key": "z_short",
            "title": "原图",
            "note": "短热翻转 · 最近均值；高=近端最热，低=近端最冷",
            "value_label": "近端均值",
            "scores": z[-extremum_n:].mean(axis=0),
            "digits": 3,
        },
        {
            "key": "approx",
            "title": "A3 粗结构",
            "note": "粗背景 · 最近均值；高=占位感强，低=粗结构偏冷",
            "value_label": "近端均值",
            "scores": a3[-extremum_n:].mean(axis=0),
            "digits": 3,
        },
        {
            "key": "d3",
            "title": "D3 中粗",
            "note": "有符号系数 · 最近均值；高=偏热（红），低=偏冷（蓝）",
            "value_label": "近端系数",
            "scores": d3[-extremum_n:].mean(axis=0),
            "digits": 4,
        },
        {
            "key": "d1",
            "title": "D1 细尺度",
            "note": "有符号系数 · 最近均值；高=正向脉冲，低=负向脉冲",
            "value_label": "近端系数",
            "scores": d1[-extremum_n:].mean(axis=0),
            "digits": 4,
        },
    ]

    out: list[dict[str, Any]] = []
    for panel in panels:
        scores = np.asarray(panel["scores"], dtype=float)
        order = np.argsort(scores, kind="mergesort")
        low_idx = order[:k]
        high_idx = order[::-1][:k]
        digits = int(panel["digits"])
        rows = _extremum_side_rows(
            names=names,
            codes=codes,
            scores=scores,
            indices=high_idx,
            side="高",
            digits=digits,
        ) + _extremum_side_rows(
            names=names,
            codes=codes,
            scores=scores,
            indices=low_idx,
            side="低",
            digits=digits,
        )
        out.append(
            {
                "key": panel["key"],
                "title": panel["title"],
                "note": panel["note"],
                "value_label": panel["value_label"],
                "rows": rows,
                "date_from": date_from,
                "date_to": date_to,
            }
        )
    return out
