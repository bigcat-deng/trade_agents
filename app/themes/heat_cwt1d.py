"""1D Morlet CWT on a board hotness series: spectrum, dominant mode, phase forecast.

Window is trading-day samples of h∈[0,1] (larger = hotter). Phase-1 forecast
keeps only the strongest near-end mode and advances its phase seamlessly from
the tip pixel.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from os import cpu_count
from typing import Any

import numpy as np
import pywt

from app.themes.heat_forecast import FORECAST_CONTEXT_DAYS, FORECAST_DAYS
from app.themes.heat_seriation import densify_hotness_plane

# Forecast-page default: no x-interpolation (cuts Plotly HTML ~5× on wide rosters).
FORECAST_PLANE_DENSIFY = 1
_CWT_POOL_WORKERS = max(2, min(8, (cpu_count() or 4)))

WINDOW_DAYS = 160
PERIOD_MIN = 4
PERIOD_MAX = 64
WAVELET = "cmor1.5-1.0"
NEAR_END_DAYS = 20
SOFT_KAPPA = 0.35
AMP_DECAY = 0.97
MIN_VALID_POINTS = 40

CWT_AXIS_NOTE = (
    "CWT 相位续推：各板用约160日短热映射为 h（板内，越大越热），"
    "取近端最强1模，自截止日像素无缝按相位推进；属结构情景，不是点预测。"
)


@dataclass(frozen=True)
class CwtMode:
    period: float
    energy_share: float
    near_amp: float
    near_amp_slope: float  # >0 expanding, <0 contracting
    phase: float
    center: float


@dataclass(frozen=True)
class AsymStats:
    up_mean_len: float | None
    down_mean_len: float | None
    up_mean_slope: float | None
    down_mean_slope: float | None


def map_heat_short_to_h(heat_short: list[float | None]) -> np.ndarray:
    """Own-window map: smaller heat_short → larger h∈[0,1]."""
    arr = np.asarray(
        [np.nan if v is None or not np.isfinite(float(v)) else float(v) for v in heat_short],
        dtype=float,
    )
    valid = arr[np.isfinite(arr)]
    if valid.size == 0:
        return np.full(arr.shape[0], np.nan, dtype=float)
    lo = float(np.min(valid))
    hi = float(np.max(valid))
    if hi <= lo + 1e-12:
        out = np.full(arr.shape[0], 0.5, dtype=float)
        out[~np.isfinite(arr)] = np.nan
        return out
    # invert: hottest (low heat_short) → 1
    h = 1.0 - (arr - lo) / (hi - lo)
    h = np.clip(h, 0.0, 1.0)
    h[~np.isfinite(arr)] = np.nan
    return h


def _scales_for_periods(periods: np.ndarray) -> np.ndarray:
    scales = np.empty(periods.shape[0], dtype=float)
    for i, p in enumerate(periods):
        lo, hi = 0.5, 200.0
        for _ in range(48):
            mid = 0.5 * (lo + hi)
            freq = float(pywt.scale2frequency(WAVELET, mid))
            per = (1.0 / freq) if freq > 0 else 1e9
            if per < float(p):
                lo = mid
            else:
                hi = mid
        scales[i] = 0.5 * (lo + hi)
    return scales


@lru_cache(maxsize=4)
def _cached_period_scales(
    period_min: int, period_max: int
) -> tuple[np.ndarray, np.ndarray]:
    periods = np.arange(int(period_min), int(period_max) + 1, dtype=float)
    return periods, _scales_for_periods(periods)


def _fill_nan_linear(h: np.ndarray) -> np.ndarray:
    x = np.arange(h.size, dtype=float)
    good = np.isfinite(h)
    if good.sum() == 0:
        return np.zeros_like(h)
    if good.all():
        return h.copy()
    out = h.copy()
    out[~good] = np.interp(x[~good], x[good], h[good])
    return out


def _linear_detrend(signal: np.ndarray) -> tuple[np.ndarray, float]:
    """Remove linear drift; return residual and the terminal trend level as center hint."""
    x = np.arange(signal.size, dtype=float)
    coef = np.polyfit(x, signal, 1)
    trend = coef[0] * x + coef[1]
    return signal - trend, float(trend[-1])


def energy_weighted_period_spectrum(
    h: np.ndarray,
    *,
    near_end_days: int = NEAR_END_DAYS,
    period_min: int = PERIOD_MIN,
    period_max: int = PERIOD_MAX,
) -> dict[str, Any]:
    """Morlet CWT → near-end-weighted power vs period (trading days)."""
    periods, scales = _cached_period_scales(int(period_min), int(period_max))
    filled = _fill_nan_linear(np.asarray(h, dtype=float))
    # Detrend so the longest scale is not just a ramp; forecast center uses tip level.
    detrended, _tip_trend = _linear_detrend(filled)
    coefs, _freqs = pywt.cwt(
        detrended, scales=scales, wavelet=WAVELET, sampling_period=1.0
    )
    power = np.abs(coefs) ** 2  # (n_scales, T)
    t = power.shape[1]
    near_n = max(3, min(int(near_end_days), t))
    w = np.ones(t, dtype=float)
    w[:-near_n] = 0.25
    w[-near_n:] = 1.0
    w /= w.sum()
    spectrum = power @ w  # (n_scales,)
    total = float(spectrum.sum())
    if total <= 0:
        spectrum_n = np.zeros_like(spectrum)
    else:
        spectrum_n = spectrum / total
    return {
        "periods": periods,
        "scales": scales,
        "spectrum": spectrum_n,
        "power": power,
        "coefs": coefs,
        "signal": filled,
        "detrended": detrended,
        "near_n": near_n,
    }


def extract_dominant_near_mode(
    h: np.ndarray,
    *,
    near_end_days: int = NEAR_END_DAYS,
    soft_kappa: float = SOFT_KAPPA,
) -> tuple[CwtMode | None, dict[str, Any]]:
    """Strongest near-end scale → one CwtMode + spectrum payload."""
    del soft_kappa  # reserved for forecast shaping
    valid_n = int(np.isfinite(h).sum())
    if valid_n < MIN_VALID_POINTS:
        return None, {"empty_message": f"valid points {valid_n} < {MIN_VALID_POINTS}"}
    pack = energy_weighted_period_spectrum(h, near_end_days=near_end_days)
    spectrum = pack["spectrum"]
    periods = pack["periods"]
    coefs = pack["coefs"]
    power = pack["power"]
    signal = pack["signal"]
    near_n = pack["near_n"]
    k = int(np.argmax(spectrum))
    period = float(periods[k])
    share = float(spectrum[k])
    tip_coef = complex(coefs[k, -1])
    phase = float(np.angle(tip_coef))
    near_amp_series = np.sqrt(power[k, -near_n:])
    near_amp = float(np.mean(near_amp_series))
    if near_n >= 4:
        x = np.arange(near_n, dtype=float)
        slope = float(np.polyfit(x, near_amp_series, 1)[0])
    else:
        slope = 0.0
    # Oscillation rides on the tip level of the original (non-detrended) series.
    original = pack["signal"]
    center = float(np.nanmean(original[-near_n:]))
    mode = CwtMode(
        period=period,
        energy_share=share,
        near_amp=near_amp,
        near_amp_slope=slope,
        phase=phase,
        center=center,
    )
    return mode, pack


def soft_asymmetric_sine(theta: np.ndarray, kappa: float = SOFT_KAPPA) -> np.ndarray:
    s = np.sin(theta)
    den = 1.0 + float(kappa) * s
    den = np.where(np.abs(den) < 1e-6, np.sign(den) * 1e-6 + 1e-6, den)
    return s / den


def asymmetry_stats(h: np.ndarray, *, min_leg: int = 3) -> AsymStats:
    """Up/down phase mean length and slope on a lightly smoothed series."""
    signal = _fill_nan_linear(np.asarray(h, dtype=float))
    if signal.size < 8:
        return AsymStats(None, None, None, None)
    # 3-point MA to reduce jitter before zero-cross relative to local center
    ker = np.ones(3) / 3.0
    sm = np.convolve(signal, ker, mode="same")
    c = float(np.mean(sm))
    x = sm - c
    # segments between consecutive zero crossings
    sign = np.sign(x)
    sign[sign == 0] = 1.0
    crosses = np.where(np.diff(sign) != 0)[0] + 1
    bounds = np.r_[0, crosses, signal.size]
    up_len: list[float] = []
    down_len: list[float] = []
    up_slope: list[float] = []
    down_slope: list[float] = []
    for i in range(len(bounds) - 1):
        a, b = int(bounds[i]), int(bounds[i + 1])
        if b - a < min_leg:
            continue
        seg = signal[a:b]
        length = float(b - a)
        slope = float(seg[-1] - seg[0]) / max(length - 1.0, 1.0)
        if float(np.mean(x[a:b])) >= 0:
            up_len.append(length)
            up_slope.append(slope)
        else:
            down_len.append(length)
            down_slope.append(slope)

    def _mean(vals: list[float]) -> float | None:
        return float(np.mean(vals)) if vals else None

    return AsymStats(
        up_mean_len=_mean(up_len),
        down_mean_len=_mean(down_len),
        up_mean_slope=_mean(up_slope),
        down_mean_slope=_mean(down_slope),
    )


def calibrate_mode_amplitude(
    signal: np.ndarray,
    mode: CwtMode,
    *,
    near_n: int,
    kappa: float = SOFT_KAPPA,
) -> float:
    """Least-squares amp in h-units so shape(phase) matches near-end residual."""
    near_n = max(3, min(int(near_n), signal.size))
    omega = 2.0 * np.pi / float(mode.period)
    idx = np.arange(near_n, dtype=float)
    # last sample aligns with mode.phase
    theta = mode.phase - omega * (near_n - 1.0 - idx)
    shape = soft_asymmetric_sine(theta, kappa)
    target = signal[-near_n:] - float(mode.center)
    denom = float(np.dot(shape, shape))
    if denom < 1e-10:
        room = max(0.05, min(mode.center, 1.0 - mode.center))
        return 0.5 * room
    amp = float(np.dot(shape, target) / denom)
    room = max(0.05, min(mode.center, 1.0 - mode.center) + 0.15)
    return float(np.clip(abs(amp), 0.0, room)) * (1.0 if amp >= 0 else -1.0)


def phase_forecast_from_mode(
    mode: CwtMode,
    *,
    amp: float,
    tip_h: float,
    n_days: int = FORECAST_DAYS,
    kappa: float = SOFT_KAPPA,
    amp_decay: float = AMP_DECAY,
) -> list[float]:
    """Seamless phase continue: wave passes through tip_h at k=0, then advance.

    Equivalent form:
      h(k) = tip_h + amp * decay^k * (shape(φ+ωk) − shape(φ))
    so the cutoff pixel is the start of the stroke, not a free re-center.
    """
    if n_days < 1 or mode.period <= 1e-6:
        return []
    tip = float(np.clip(tip_h, 0.0, 1.0))
    omega = 2.0 * np.pi / float(mode.period)
    shape0 = float(soft_asymmetric_sine(np.array([mode.phase]), kappa)[0])
    out: list[float] = []
    for k in range(1, n_days + 1):
        theta = mode.phase + omega * k
        shape = float(soft_asymmetric_sine(np.array([theta]), kappa)[0])
        a = float(amp) * (amp_decay ** k)
        val = float(np.clip(tip + a * (shape - shape0), 0.0, 1.0))
        out.append(val)
    return out


def analyze_board_series(
    heat_short: list[float | None],
    *,
    near_end_days: int = NEAR_END_DAYS,
    light: bool = False,
) -> dict[str, Any]:
    """Full per-board pack: h, mode, spectrum, asymmetry, 5-day forecast.

    ``light=True`` skips asymmetry / spectrum lists (forecast-plane path).
    """
    h = map_heat_short_to_h(heat_short)
    mode, pack = extract_dominant_near_mode(h, near_end_days=near_end_days)
    asym = None if light else asymmetry_stats(h)
    if mode is None:
        out = {
            "h": h.tolist(),
            "mode": None,
            "asym": asym,
            "forecast": [],
            "amp": None,
            "tip_h": None,
            "empty_message": pack.get("empty_message"),
        }
        if not light:
            out["spectrum_periods"] = (
                pack["periods"].tolist()
                if isinstance(pack.get("periods"), np.ndarray)
                else pack.get("periods")
            )
            out["spectrum"] = (
                pack["spectrum"].tolist()
                if isinstance(pack.get("spectrum"), np.ndarray)
                else pack.get("spectrum")
            )
        return out
    tip_h = next(
        (float(v) for v in reversed(h.tolist()) if v is not None and np.isfinite(v)),
        float(mode.center),
    )
    # Fit amp on detrended residual; tip_h anchors the stroke start.
    amp = calibrate_mode_amplitude(
        pack["detrended"],
        CwtMode(
            period=mode.period,
            energy_share=mode.energy_share,
            near_amp=mode.near_amp,
            near_amp_slope=mode.near_amp_slope,
            phase=mode.phase,
            center=0.0,
        ),
        near_n=pack["near_n"],
    )
    forecast = phase_forecast_from_mode(mode, amp=amp, tip_h=tip_h)
    out = {
        "h": h.tolist(),
        "mode": mode,
        "asym": asym,
        "forecast": forecast,
        "amp": amp,
        "tip_h": tip_h,
        "empty_message": None,
        "amp_trend": (
            "expanding"
            if mode.near_amp_slope > 1e-4
            else ("contracting" if mode.near_amp_slope < -1e-4 else "flat")
        ),
    }
    if not light:
        out["spectrum_periods"] = pack["periods"].tolist()
        out["spectrum"] = pack["spectrum"].tolist()
    return out


def build_industry_cwt_forecast_plane(
    *,
    tip: date,
    hist: list[date],
    heat_by_day: dict[date, dict[str, float]],
    names: dict[str, str],
    ordered: list[str],
    forecast_dates: list[date],
    context_days: int = FORECAST_CONTEXT_DAYS,
    densify: int = FORECAST_PLANE_DENSIFY,
) -> dict[str, Any]:
    """Context own-window h + seamless 1-mode phase forecast, densified for plot."""
    if not hist or not ordered or not forecast_dates:
        return {
            "empty_message": "CWT 相位续推缺少历史或推演日",
            "as_of": tip.isoformat(),
        }

    def _analyze_one(code: str) -> tuple[str, dict[str, Any]]:
        hs = [(heat_by_day.get(day) or {}).get(code) for day in hist]
        return code, analyze_board_series(hs, light=True)

    analyses: dict[str, dict[str, Any]] = {}
    h_by_code: dict[str, list[float | None]] = {}
    workers = min(_CWT_POOL_WORKERS, max(1, len(ordered)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for code, pack in pool.map(_analyze_one, ordered):
            analyses[code] = pack
            raw_h = pack.get("h") or []
            h_by_code[code] = [
                None
                if v is None or (isinstance(v, float) and not np.isfinite(v))
                else float(v)
                for v in raw_h
            ]

    ctx_n = max(5, min(int(context_days), len(hist)))
    context = hist[-ctx_n:]
    ctx_offset = len(hist) - ctx_n
    z_hist: list[list[float | None]] = []
    for i in range(ctx_offset, len(hist)):
        z_hist.append([h_by_code[c][i] if i < len(h_by_code[c]) else None for c in ordered])

    z_fwd: list[list[float | None]] = []
    for j in range(len(forecast_dates)):
        row: list[float | None] = []
        for code in ordered:
            fc = analyses[code].get("forecast") or []
            row.append(float(fc[j]) if j < len(fc) else None)
        z_fwd.append(row)

    z_native = z_hist + z_fwd
    display_dates = list(context) + list(forecast_dates)
    x_ticks = list(range(len(ordered)))
    densify_n = max(1, int(densify))
    dense_x, dense_z = densify_hotness_plane(
        theme_x=[float(i) for i in x_ticks],
        z_short=z_native,
        densify=densify_n,
    )
    labels = [names.get(c, c) for c in ordered]

    # Short scenario line: median period + contracting share among boards with modes
    periods: list[float] = []
    contracting = 0
    expanding = 0
    for code in ordered:
        m = analyses[code].get("mode")
        if m is None:
            continue
        periods.append(float(m.period))
        trend = analyses[code].get("amp_trend")
        if trend == "contracting":
            contracting += 1
        elif trend == "expanding":
            expanding += 1
    if periods:
        med = float(np.median(periods))
        scenario_note = (
            f"近端主模周期中位 {med:.0f} 日；振幅扩张 {expanding} / 收缩 {contracting} / "
            f"共 {len(periods)} 板有主模。窗长 {len(hist)} 日。"
        )
    else:
        scenario_note = "未能提取有效主模。"

    return {
        "dates": [d.isoformat() for d in display_dates],
        "board_codes": ordered,
        "board_names": labels,
        "x": dense_x,
        "x_tickvals": [float(i) for i in x_ticks],
        "x_ticktext": labels,
        "z_short": dense_z,
        "z_boards": z_native,
        "axis_note": CWT_AXIS_NOTE,
        "as_of": tip.isoformat(),
        "forecast_dates": [d.isoformat() for d in forecast_dates],
        "context_dates": [d.isoformat() for d in context],
        "board_count": len(ordered),
        "scenario_note": scenario_note,
        "empty_message": None,
        "densify": densify_n,
        "window_days": len(hist),
    }
