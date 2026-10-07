"""Cross-section regime from persistent hot cores (主线 = 持续高热凝练核).

Main theme is the leaf-order connected run of industries that stay hot near
the as-of edge. Spreading / expanding is NOT required — a narrow persistent
core counts as condensed strength.

States (priority fade > dominate > none):

  dominate  persistent core is hot enough and leads heat-mass (or heat gap)
  fade      recent dominate lineage still matched, but heat / lead is retreating
  none      no core meets dominate gates
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

import numpy as np

# Near-end persistence window (trading days on the plane).
PERSIST_DAYS = 6
# Column must stay hot: as-of, window mean, and enough hot days.
H_ASOF = 0.70
H_MEAN = 0.70
H_DAY = 0.65
MIN_HOT_DAYS = 4

# Dominate gates (width may be 1 — 凝练).
H_MIN = 0.75
S_MIN = 0.35
H_GAP_MIN = 0.05

JACCARD_KEEP = 0.5
DOMINANCE_LOOKBACK = 8
H_DROP = 0.05
S_DROP = 0.05

REGIME_DOMINATE = "主线统治"
REGIME_FADE = "主线衰落"
REGIME_NONE = "无主线"

LICENSE_WATCH = "可关注"
LICENSE_PRESSURE = "受压"
LICENSE_EMPTY = "—"

# Warming candidates: near-end rim patches outside the main core.
CAND_MAX_WIDTH = 5
CAND_TOP_N = 3
CAND_MAX_MAIN_OVERLAP = 0.5

# Web panel: show last N days; compute extra days so fade lineage is warm.
REGIME_DISPLAY_DAYS = 10
REGIME_WARMUP_DAYS = 16
REGIME_PLANE_WINDOW = 40


@dataclass(frozen=True)
class CoreSnap:
    codes: frozenset[str]
    label: str
    width: int
    mean_heat: float
    asof_heat: float
    peak_persist: float
    peak_asof: float
    heat_mass: float
    persist_days: int
    members: str
    lo: int
    hi: int


@dataclass
class Lineage:
    codes: frozenset[str]
    label: str
    peak_h: float
    peak_s: float
    last_dominate: date | None = None


@dataclass(frozen=True)
class CandidateSnap:
    codes: frozenset[str]
    label: str
    members: str
    width: int
    lo: int
    hi: int
    expanding: bool
    brightening: bool
    n_edge: int
    mean_heat: float
    relation: str


@dataclass(frozen=True)
class DayRegime:
    signal_date: date
    regime: str
    label: str
    members: str
    w: int
    w2: int
    s: float
    h: float
    h2: float
    k: int
    jaccard_prev: float
    dominate_ok: bool
    fade_flags: str
    lineage_label: str
    cand_label: str = ""
    cand_members: str = ""
    cand_w: str = ""
    cand_relation: str = ""
    cand_license: str = LICENSE_EMPTY
    cand_n: int = 0


def list_persistent_hot_cores(
    *,
    dates: list[date],
    codes: list[str],
    names: list[str],
    z: list[list[float | None]] | np.ndarray,
    persist_days: int = PERSIST_DAYS,
) -> dict[str, Any]:
    """Connected leaf-order runs of near-end persistently hot columns."""
    empty: dict[str, Any] = {"as_of": None, "cores": []}
    if not dates or not codes or z is None:
        return empty
    grid = np.asarray(z, dtype=float)
    if grid.ndim != 2 or grid.size == 0:
        return empty
    n_t, n_c = grid.shape
    if n_c != len(codes) or n_t != len(dates):
        return empty
    finite_rows = np.isfinite(grid).any(axis=1)
    if not bool(finite_rows.any()):
        return empty
    t_end = int(np.max(np.flatnonzero(finite_rows)))
    p = max(2, min(int(persist_days), t_end + 1))
    t0 = t_end - p + 1
    mask = np.zeros(n_c, dtype=bool)
    persist_mean = np.full(n_c, np.nan)
    asof = grid[t_end]
    for i in range(n_c):
        series = grid[t0 : t_end + 1, i]
        finite = series[np.isfinite(series)]
        if finite.size < MIN_HOT_DAYS:
            continue
        a = asof[i]
        if not np.isfinite(a) or float(a) < H_ASOF:
            continue
        mu = float(finite.mean())
        if mu < H_MEAN:
            continue
        hot_days = int(np.count_nonzero(finite >= H_DAY))
        if hot_days < MIN_HOT_DAYS:
            continue
        mask[i] = True
        persist_mean[i] = mu

    cores: list[dict[str, Any]] = []
    for lo, hi in _true_runs(mask):
        members: list[dict[str, Any]] = []
        masses: list[float] = []
        means: list[float] = []
        asofs: list[float] = []
        for i in range(lo, hi):
            a = float(asof[i])
            mu = float(persist_mean[i])
            name = names[i] if i < len(names) else codes[i]
            members.append(
                {
                    "board_code": codes[i],
                    "board_name": name,
                    "col": i,
                    "hotness_asof": round(a, 3),
                    "hotness_persist": round(mu, 3),
                }
            )
            masses.append(a)
            means.append(mu)
            asofs.append(a)
        left = names[lo] if lo < len(names) else codes[lo]
        right = names[hi - 1] if hi - 1 < len(names) else codes[hi - 1]
        cores.append(
            {
                "lo": lo,
                "hi": hi,
                "width": hi - lo,
                "label": f"{left} → {right}",
                "mean_heat": round(float(np.mean(means)), 3),
                "asof_heat": round(float(np.mean(asofs)), 3),
                "peak_persist": round(float(max(means)), 3),
                "peak_asof": round(float(max(asofs)), 3),
                "heat_mass": round(float(sum(masses)), 3),
                "persist_days": p,
                "members": members,
            }
        )
    empty["as_of"] = dates[t_end].isoformat()
    empty["cores"] = cores
    return empty


def cores_from_listed(listed: dict[str, Any]) -> list[CoreSnap]:
    out: list[CoreSnap] = []
    for core in listed.get("cores") or []:
        members = list(core.get("members") or [])
        if not members:
            continue
        peak_persist = float(core.get("peak_persist") or 0.0)
        peak_asof = float(core.get("peak_asof") or 0.0)
        if not peak_persist and members:
            peak_persist = max(float(m.get("hotness_persist") or 0.0) for m in members)
        if not peak_asof and members:
            peak_asof = max(float(m.get("hotness_asof") or 0.0) for m in members)
        out.append(
            CoreSnap(
                codes=frozenset(str(m["board_code"]) for m in members),
                label=str(core.get("label") or ""),
                width=int(core.get("width") or 0),
                mean_heat=float(core.get("mean_heat") or 0.0),
                asof_heat=float(core.get("asof_heat") or 0.0),
                peak_persist=peak_persist,
                peak_asof=peak_asof,
                heat_mass=float(core.get("heat_mass") or 0.0),
                persist_days=int(core.get("persist_days") or PERSIST_DAYS),
                members=",".join(
                    str(m.get("board_name") or m.get("board_code")) for m in members
                ),
                lo=int(core.get("lo") or 0),
                hi=int(core.get("hi") or 0),
            )
        )
    return out


def pick_main(cores: Iterable[CoreSnap]) -> CoreSnap | None:
    """Core holding the hottest as-of cell among persistent columns.

    As-of peak first (who is hottest now while still persistent), then
    persistence mean, then narrower (凝练).
    """
    items = list(cores)
    if not items:
        return None
    return max(
        items,
        key=lambda c: (
            c.peak_asof,
            c.peak_persist,
            c.mean_heat,
            -c.width,
            tuple(sorted(c.codes)),
        ),
    )


def heat_share(main: CoreSnap, cores: list[CoreSnap]) -> float:
    total = sum(c.heat_mass for c in cores)
    if total <= 0:
        return 0.0
    return main.heat_mass / total


def second_core(main: CoreSnap, cores: list[CoreSnap]) -> CoreSnap | None:
    others = [c for c in cores if c.codes != main.codes]
    if not others:
        return None
    return pick_main(others)


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def best_match(
    members: frozenset[str], cores: list[CoreSnap]
) -> tuple[CoreSnap | None, float]:
    best: CoreSnap | None = None
    best_j = -1.0
    for core in cores:
        jac = jaccard(members, core.codes)
        if jac > best_j:
            best_j = jac
            best = core
    if best is None:
        return None, 0.0
    return best, best_j


def is_dominate(
    *,
    h: float,
    s: float,
    h2: float,
    h_min: float = H_MIN,
    s_min: float = S_MIN,
    h_gap_min: float = H_GAP_MIN,
) -> bool:
    if h < h_min:
        return False
    return s >= s_min or (h - h2) >= h_gap_min


def fade_flag_list(
    *,
    matched: CoreSnap | None,
    s: float,
    h2: float,
    lineage: Lineage,
    in_cores: bool,
) -> list[str]:
    flags: list[str] = []
    if not in_cores or matched is None:
        flags.append("lost_persist")
        if lineage.peak_h - (matched.peak_persist if matched else 0.0) >= H_DROP:
            flags.append("h_drop")
        if lineage.peak_s - s >= S_DROP:
            flags.append("s_drop")
        return flags
    if lineage.peak_h - matched.peak_persist >= H_DROP:
        flags.append("h_drop")
    if lineage.peak_s - s >= S_DROP:
        flags.append("s_drop")
    if not is_dominate(h=matched.peak_persist, s=s, h2=h2):
        flags.append("lead_lost")
    return flags


def candidate_license(regime: str) -> str:
    if regime == REGIME_DOMINATE:
        return LICENSE_PRESSURE
    if regime in (REGIME_FADE, REGIME_NONE):
        return LICENSE_WATCH
    return LICENSE_EMPTY


def list_warming_candidates(
    *,
    dates: list[date],
    codes: list[str],
    names: list[str],
    z: list[list[float | None]] | np.ndarray,
    main: CoreSnap | None,
    top_n: int = CAND_TOP_N,
    started_codes: frozenset[str] | Iterable[str] | None = None,
) -> list[CandidateSnap]:
    """Near-end expanding/brightening patches outside the main persistent core.

    Patches whose outside members already show near-end launch or exhaustion
    (``started_codes``: big-yang, volume surge, big-yin, long upper shadow)
    are dropped — keep not-yet-launched, non-rollover names.
    """
    from app.themes.heat_rim_spread import list_heat_rim_patches

    listed = list_heat_rim_patches(
        dates=dates, codes=codes, names=names, z=z, include_inactive=False
    )
    main_codes = main.codes if main is not None else frozenset()
    main_lo = main.lo if main is not None else -1
    main_hi = main.hi if main is not None else -1
    started = frozenset(str(c) for c in (started_codes or ()))
    scored: list[tuple[tuple, CandidateSnap]] = []
    for patch in listed.get("patches") or []:
        members = list(patch.get("members") or [])
        if not members:
            continue
        codes_set = frozenset(str(m["board_code"]) for m in members)
        if not codes_set:
            continue
        overlap = jaccard(codes_set, main_codes)
        if overlap >= CAND_MAX_MAIN_OVERLAP:
            continue
        outside = codes_set - main_codes
        if not outside:
            continue
        # Drop blocks that already fired on price/volume.
        if started and outside & started:
            continue
        width = int(patch.get("width_now") or len(members))
        if width > CAND_MAX_WIDTH and not bool(patch.get("expanding")):
            continue
        lo = int(patch.get("lo") or 0)
        hi = int(patch.get("hi") or 0)
        n_edge = sum(1 for m in members if m.get("role") == "边")
        expanding = bool(patch.get("expanding"))
        brightening = bool(patch.get("brightening"))
        mean_heat = float(patch.get("mean_heat") or 0.0)
        relation = _candidate_relation(lo, hi, main_lo, main_hi, overlap)
        # Keep only outside names in display when overlap is partial.
        show = [m for m in members if str(m["board_code"]) in outside]
        if not show:
            show = members
        left = str(show[0].get("board_name") or show[0]["board_code"])
        right = str(show[-1].get("board_name") or show[-1]["board_code"])
        label = f"{left} → {right}"
        member_str = ",".join(
            str(m.get("board_name") or m.get("board_code")) for m in show
        )
        cand = CandidateSnap(
            codes=frozenset(str(m["board_code"]) for m in show),
            label=label,
            members=member_str,
            width=len(show),
            lo=lo,
            hi=hi,
            expanding=expanding,
            brightening=brightening,
            n_edge=n_edge,
            mean_heat=mean_heat,
            relation=relation,
        )
        # Prefer: more edge, expanding, brighter, narrower, less overlap with main.
        key = (
            n_edge / max(1, width),
            int(expanding),
            int(brightening),
            mean_heat,
            -width,
            -overlap,
            label,
        )
        scored.append((key, cand))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [cand for _, cand in scored[: max(1, int(top_n))]]


def _candidate_relation(
    lo: int, hi: int, main_lo: int, main_hi: int, overlap: float
) -> str:
    if main_lo < 0 or main_hi < 0:
        return "带外新亮"
    if overlap > 0:
        return "邻域外溢"
    # Touch or within one column of the main span.
    if hi >= main_lo - 1 and lo <= main_hi + 1:
        return "邻域外溢"
    return "带外新亮"


def with_candidates(row: DayRegime, candidates: list[CandidateSnap]) -> DayRegime:
    if not candidates:
        return DayRegime(
            **{
                **row.__dict__,
                "cand_label": "",
                "cand_members": "",
                "cand_w": "",
                "cand_relation": "",
                "cand_license": LICENSE_EMPTY,
                "cand_n": 0,
            }
        )
    return DayRegime(
        **{
            **row.__dict__,
            "cand_label": "; ".join(c.label for c in candidates),
            "cand_members": "; ".join(c.members for c in candidates),
            "cand_w": "; ".join(str(c.width) for c in candidates),
            "cand_relation": "; ".join(c.relation for c in candidates),
            "cand_license": candidate_license(row.regime),
            "cand_n": len(candidates),
        }
    )


def label_day(
    *,
    signal_date: date,
    cores: list[CoreSnap],
    prev_main: CoreSnap | None,
    lineage: Lineage | None,
    had_recent_dominate: bool,
) -> tuple[DayRegime, Lineage | None, CoreSnap | None]:
    main = pick_main(cores)
    if main is None:
        return (
            DayRegime(
                signal_date=signal_date,
                regime=REGIME_NONE,
                label="",
                members="",
                w=0,
                w2=0,
                s=0.0,
                h=0.0,
                h2=0.0,
                k=0,
                jaccard_prev=0.0,
                dominate_ok=False,
                fade_flags="",
                lineage_label=lineage.label if lineage else "",
            ),
            lineage,
            None,
        )

    other = second_core(main, cores)
    w = main.width
    w2 = other.width if other else 0
    s = heat_share(main, cores)
    h = main.peak_persist
    h2 = other.peak_persist if other else 0.0
    k = len(cores)
    jac_prev = jaccard(prev_main.codes, main.codes) if prev_main else 0.0
    dominate_ok = is_dominate(h=h, s=s, h2=h2)

    matched_lineage: CoreSnap | None = None
    jac_lineage = 0.0
    if lineage is not None:
        matched_lineage, jac_lineage = best_match(lineage.codes, cores)

    fade_flags: list[str] = []
    regime = REGIME_NONE
    in_cores = False
    if had_recent_dominate and lineage is not None:
        in_cores = matched_lineage is not None and jac_lineage >= JACCARD_KEEP
        matched_s = (
            heat_share(matched_lineage, cores) if matched_lineage is not None else 0.0
        )
        matched_other = (
            second_core(matched_lineage, cores) if matched_lineage is not None else None
        )
        matched_h2 = matched_other.peak_persist if matched_other else 0.0
        fade_flags = fade_flag_list(
            matched=matched_lineage,
            s=matched_s,
            h2=matched_h2,
            lineage=lineage,
            in_cores=in_cores,
        )
    same_lineage = (
        in_cores
        and matched_lineage is not None
        and jaccard(matched_lineage.codes, main.codes) >= JACCARD_KEEP
    )
    if dominate_ok and not (same_lineage and len(fade_flags) >= 2):
        regime = REGIME_DOMINATE
    elif had_recent_dominate and lineage is not None and len(fade_flags) >= 2:
        regime = REGIME_FADE
    elif dominate_ok:
        regime = REGIME_DOMINATE

    new_lineage = lineage
    if regime == REGIME_DOMINATE:
        if (
            new_lineage is not None
            and jaccard(new_lineage.codes, main.codes) >= JACCARD_KEEP
        ):
            new_lineage = Lineage(
                codes=main.codes,
                label=main.label,
                peak_h=max(new_lineage.peak_h, h),
                peak_s=max(new_lineage.peak_s, s),
                last_dominate=signal_date,
            )
        else:
            new_lineage = Lineage(
                codes=main.codes,
                label=main.label,
                peak_h=h,
                peak_s=s,
                last_dominate=signal_date,
            )
    elif regime == REGIME_FADE and matched_lineage is not None and new_lineage is not None:
        new_lineage = Lineage(
            codes=matched_lineage.codes,
            label=matched_lineage.label,
            peak_h=new_lineage.peak_h,
            peak_s=new_lineage.peak_s,
            last_dominate=new_lineage.last_dominate,
        )

    row = DayRegime(
        signal_date=signal_date,
        regime=regime,
        label=main.label,
        members=main.members,
        w=w,
        w2=w2,
        s=round(s, 4),
        h=round(h, 3),
        h2=round(h2, 3),
        k=k,
        jaccard_prev=round(jac_prev, 4),
        dominate_ok=dominate_ok,
        fade_flags=",".join(fade_flags),
        lineage_label=new_lineage.label if new_lineage else "",
    )
    return row, new_lineage, main


def label_series(
    daily_cores: list[tuple[date, list[CoreSnap]]]
    | list[tuple[date, list[CoreSnap], dict[str, Any]]],
    *,
    lookback: int = DOMINANCE_LOOKBACK,
) -> list[DayRegime]:
    """Label regimes; optional 3rd tuple item is plane ``{dates,codes,names,z}``."""
    rows: list[DayRegime] = []
    prev_main: CoreSnap | None = None
    lineage: Lineage | None = None
    dominate_idxs: list[int] = []
    date_index = {item[0]: i for i, item in enumerate(daily_cores)}

    for i, item in enumerate(daily_cores):
        day = item[0]
        cores = item[1]
        plane = item[2] if len(item) > 2 else None
        dominate_idxs = [j for j in dominate_idxs if i - j < lookback]
        row, lineage, main = label_day(
            signal_date=day,
            cores=cores,
            prev_main=prev_main,
            lineage=lineage,
            had_recent_dominate=bool(dominate_idxs),
        )
        if row.regime == REGIME_DOMINATE:
            dominate_idxs.append(i)
        if (
            lineage is not None
            and lineage.last_dominate is not None
            and row.regime == REGIME_NONE
        ):
            last_i = date_index.get(lineage.last_dominate)
            if last_i is not None and i - last_i >= lookback:
                lineage = None
                row = DayRegime(**{**row.__dict__, "lineage_label": ""})
        if plane:
            cands = list_warming_candidates(
                dates=list(plane["dates"]),
                codes=list(plane["codes"]),
                names=list(plane["names"]),
                z=plane["z"],
                main=main,
                started_codes=plane.get("started_codes"),
            )
            row = with_candidates(row, cands)
        rows.append(row)
        prev_main = main
    return rows


def build_regime_panel_payload(
    *,
    as_of: date,
    calendar: list[date],
    heat_by_day: dict[date, dict[str, float]],
    names: dict[str, str],
    display_days: int = REGIME_DISPLAY_DAYS,
    warmup_days: int = REGIME_WARMUP_DAYS,
    window_days: int = REGIME_PLANE_WINDOW,
    bars_by_code: dict[str, list[dict[str, Any]]] | None = None,
    vol_calendar: list[date] | None = None,
) -> dict[str, Any]:
    """On-request regime+candidate rows for the theme-wave industry panel.

    Computes ``display_days + warmup_days`` signal days (lineage warm-up),
    returns only the last ``display_days`` for the table. No file cache.
    When ``bars_by_code`` is set, candidates already showing near-end launch
    (big-yang / volume surge) or exhaustion (big-yin / long upper shadow)
    are dropped.
    """
    from app.themes.industry_return_flags import collect_started_codes

    empty = {
        "rows": [],
        "note": "近端没有可标的主线政权。",
        "as_of": as_of.isoformat(),
        "display_days": int(display_days),
    }
    if not calendar:
        return empty

    date_index = {day: i for i, day in enumerate(calendar)}
    if as_of in date_index:
        last_i = date_index[as_of]
    else:
        last_i = max((i for d, i in date_index.items() if d <= as_of), default=-1)
    if last_i < 0:
        return empty

    show_n = max(1, int(display_days))
    warm_n = max(0, int(warmup_days))
    win = max(PERSIST_DAYS + 2, int(window_days))
    need_signals = show_n + warm_n
    first_signal_i = last_i - need_signals + 1
    if first_signal_i < win - 1:
        first_signal_i = win - 1
    if first_signal_i > last_i:
        return empty
    signal_dates = calendar[first_signal_i : last_i + 1]
    vol_cal = list(vol_calendar or calendar)
    bars = bars_by_code or {}

    daily: list[tuple] = []
    for day in signal_dates:
        day_i = date_index[day]
        window = calendar[day_i - win + 1 : day_i + 1]
        plane = _plane_for_day(
            window_dates=window, heat_by_day=heat_by_day, names=names
        )
        if bars and plane["codes"]:
            plane["started_codes"] = collect_started_codes(
                codes=list(plane["codes"]),
                as_of=day,
                bars_by_code=bars,
                vol_calendar=vol_cal,
            )
        else:
            plane["started_codes"] = frozenset()
        listed = list_persistent_hot_cores(
            dates=plane["dates"],
            codes=plane["codes"],
            names=plane["names"],
            z=plane["z"],
        )
        daily.append((day, cores_from_listed(listed), plane))

    regimes = label_series(daily, lookback=DOMINANCE_LOOKBACK)
    shown = regimes[-show_n:] if regimes else []
    rows = [_panel_row(row) for row in shown]
    tip = shown[-1].signal_date.isoformat() if shown else as_of.isoformat()
    filter_bit = (
        "候选已剔除近端大阳/放量/大阴/长上影（已启动或乏力）。"
        if bars
        else ""
    )
    note = (
        f"主线=近端持续高热凝练核；候选=主线外近端铺开/加亮（最多{CAND_TOP_N}段）。"
        f"{filter_bit}"
        f"许可：统治→受压，衰落/无主线→可关注。"
        f"表内为截止 {tip} 前近 {len(rows)} 个交易日（现算，无缓存）。"
    )
    return {
        "rows": rows,
        "note": note,
        "as_of": tip,
        "display_days": len(rows),
    }


def _panel_row(row: DayRegime) -> dict[str, Any]:
    return {
        "signal_date": row.signal_date.isoformat(),
        "regime": row.regime,
        "members": row.members or "—",
        "cand_license": row.cand_license or LICENSE_EMPTY,
        "cand_members": row.cand_members or "—",
        "cand_relation": row.cand_relation or "—",
    }


def _plane_for_day(
    *,
    window_dates: list[date],
    heat_by_day: dict[date, dict[str, float]],
    names: dict[str, str],
) -> dict[str, Any]:
    from app.themes.heat_seriation import (
        hotness_grid,
        hotness_series_by_code,
        order_by_trajectory_seriation,
    )

    codes = sorted(
        {
            code
            for day in window_dates
            for code in (heat_by_day.get(day) or {})
        }
    )
    if not codes:
        return {
            "dates": window_dates,
            "codes": [],
            "names": [],
            "z": [],
        }
    series = hotness_series_by_code(
        window_dates=window_dates, codes=codes, heat_by_day=heat_by_day
    )
    ordered = order_by_trajectory_seriation(codes, series)
    labels = [names.get(code, code) for code in ordered]
    z = hotness_grid(
        window_dates=window_dates, ordered_codes=ordered, heat_by_day=heat_by_day
    )
    return {
        "dates": window_dates,
        "codes": ordered,
        "names": labels,
        "z": z,
    }


def _true_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    n = int(mask.size)
    i = 0
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i + 1
        while j < n and mask[j]:
            j += 1
        runs.append((i, j))
        i = j
    return runs
