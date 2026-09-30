"""Badge rules for concept theme heat consistency.

Heat is heat_short (smaller = hotter). Window change:
  Δ = heat(d0) − heat(as_of); >0 means getting hotter.
Percentile p in [0, 1]: 0 = hottest that day among non-null concept heats.

Group A and A↔B direction badges (同热/同冷/同向) prefer near-end
heat_short OLS slopes over the last trend_k days when series are available;
window Δ remains in numeric fields and may appear as a contrast note.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Mapping, Sequence

from app.themes.config import ThemeConfig


SIGN_FLAT = 0
SIGN_HOT = 1
SIGN_COLD = -1


@dataclass(frozen=True)
class MemberWindow:
    board_code: str
    board_name: str
    heat_d0: float | None
    heat_as_of: float | None
    pct_d0: float | None
    pct_as_of: float | None
    delta: float | None
    sign: int | None
    role: str | None = None


@dataclass(frozen=True)
class GroupBadge:
    label: str
    detail: str
    delta: float | None
    spread_d0: float | None = None
    spread_as_of: float | None = None
    co_move_ratio: float | None = None


@dataclass(frozen=True)
class PairBadge:
    label: str
    sublabel: str | None
    detail: str
    delta_a: float | None
    delta_b: float | None
    gap_d0: float | None
    gap_as_of: float | None


@dataclass(frozen=True)
class SatelliteBadge:
    board_code: str
    board_name: str
    label: str
    detail: str
    delta: float | None
    percentile_as_of: float | None


def window_delta(heat_d0: float | None, heat_as_of: float | None) -> float | None:
    if heat_d0 is None or heat_as_of is None:
        return None
    return heat_d0 - heat_as_of


def sign_delta(delta: float | None, epsilon: float) -> int | None:
    if delta is None:
        return None
    if abs(delta) <= epsilon:
        return SIGN_FLAT
    return SIGN_HOT if delta > 0 else SIGN_COLD


def average_ranks(values: Sequence[float]) -> list[float]:
    """1-based average ranks; lower value → better (hotter) rank."""
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg
        i = j + 1
    return ranks


def percentiles_from_heats(heats: Mapping[str, float]) -> dict[str, float]:
    """Map board_code → p in [0, 1], 0 = hottest."""
    if not heats:
        return {}
    codes = list(heats.keys())
    values = [heats[code] for code in codes]
    ranks = average_ranks(values)
    n = len(values)
    if n == 1:
        return {codes[0]: 0.0}
    return {code: (rank - 1.0) / (n - 1.0) for code, rank in zip(codes, ranks)}


def group_median(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return float(median(present))


def _spread(pcts: Sequence[float | None]) -> float | None:
    present = [value for value in pcts if value is not None]
    if len(present) < 2:
        return None
    return max(present) - min(present)


def build_members(
    boards: Sequence[tuple[str, str]],
    heat_d0: Mapping[str, float | None],
    heat_as_of: Mapping[str, float | None],
    pct_d0: Mapping[str, float | None],
    pct_as_of: Mapping[str, float | None],
    epsilon: float,
) -> list[MemberWindow]:
    members: list[MemberWindow] = []
    for code, name in boards:
        h0 = heat_d0.get(code)
        h1 = heat_as_of.get(code)
        delta = window_delta(h0, h1)
        members.append(
            MemberWindow(
                board_code=code,
                board_name=name,
                heat_d0=h0,
                heat_as_of=h1,
                pct_d0=pct_d0.get(code),
                pct_as_of=pct_as_of.get(code),
                delta=delta,
                sign=sign_delta(delta, epsilon),
            )
        )
    return _assign_roles(members, epsilon)


def _assign_roles(members: list[MemberWindow], epsilon: float) -> list[MemberWindow]:
    valid = [m for m in members if m.delta is not None]
    if not valid:
        return members
    leader = max(valid, key=lambda m: m.delta if m.delta is not None else float("-inf"))
    out: list[MemberWindow] = []
    for member in members:
        if member.delta is None or member.sign is None:
            role = None
        elif member.board_code == leader.board_code and member.delta > epsilon:
            role = "带"
        elif member.sign == SIGN_COLD:
            role = "掉队"
        elif member.sign == SIGN_HOT:
            role = "跟随"
        else:
            role = "平"
        out.append(
            MemberWindow(
                board_code=member.board_code,
                board_name=member.board_name,
                heat_d0=member.heat_d0,
                heat_as_of=member.heat_as_of,
                pct_d0=member.pct_d0,
                pct_as_of=member.pct_as_of,
                delta=member.delta,
                sign=member.sign,
                role=role,
            )
        )
    return out


def _ols_slope(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    var_x = sum((x - x_mean) ** 2 for x in xs)
    if var_x == 0:
        return None
    cov = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    return cov / var_x


def warming_slope_from_heats(
    heats: Sequence[float | None],
    *,
    k: int = 5,
    min_points: int = 4,
) -> float | None:
    """OLS on last k heat_short points; return −β so >0 means warming."""
    if k < 2:
        return None
    window = list(heats)[-k:]
    xs: list[float] = []
    ys: list[float] = []
    for index, heat in enumerate(window):
        if heat is None:
            continue
        xs.append(float(index))
        ys.append(float(heat))
    if len(xs) < min_points:
        return None
    raw = _ols_slope(xs, ys)
    if raw is None:
        return None
    return -raw


def sign_from_warming_slope(
    warming: float | None,
    epsilon_slope: float,
) -> int | None:
    """Map near-end warming slope to SIGN_*; >0 means getting hotter."""
    if warming is None:
        return None
    if abs(warming) <= epsilon_slope:
        return SIGN_FLAT
    return SIGN_HOT if warming > 0 else SIGN_COLD


def near_end_sign_from_heats(
    heats: Sequence[float | None],
    theme: ThemeConfig,
) -> int | None:
    return sign_from_warming_slope(
        warming_slope_from_heats(heats, k=theme.trend_k),
        theme.epsilon_slope,
    )


def _member_near_slopes(
    members: Sequence[MemberWindow],
    heat_by_code: Mapping[str, Sequence[float | None]],
    theme: ThemeConfig,
) -> dict[str, float | None]:
    return {
        m.board_code: warming_slope_from_heats(
            heat_by_code.get(m.board_code, ()), k=theme.trend_k
        )
        for m in members
    }


def _trend_word(
    warming: float | None,
    *,
    epsilon_slope: float,
    window_delta: float | None,
    window_days: int,
) -> str | None:
    if warming is None:
        return None
    if abs(warming) <= epsilon_slope:
        return "走平"
    if warming < 0:
        return "回落"
    if (
        window_delta is not None
        and window_days > 1
        and window_delta > 0
    ):
        avg_daily = window_delta / (window_days - 1)
        if avg_daily > epsilon_slope and warming < 0.5 * avg_daily:
            return "升温放缓"
    return "仍升温"


def _others_trend_phrase(
    slopes: Sequence[float | None],
    epsilon_slope: float,
) -> str:
    present = [slope for slope in slopes if slope is not None]
    if not present:
        return "其余近端不足"
    n_up = sum(1 for slope in present if slope > epsilon_slope)
    n_down = sum(1 for slope in present if slope < -epsilon_slope)
    if n_up == 0 and n_down == 0:
        return "其余走平"
    if n_up > 0 and n_down == 0:
        return "其余跟上升温"
    if n_down > 0 and n_up == 0:
        return "其余回落"
    return "其余近端分化"


def _append_recent_trend(
    detail: str,
    members: Sequence[MemberWindow],
    theme: ThemeConfig,
    heat_by_code: Mapping[str, Sequence[float | None]] | None,
    window_days: int | None,
) -> str:
    if not heat_by_code:
        return detail
    valid = [m for m in members if m.sign is not None and m.delta is not None]
    if len(valid) < 2:
        return detail
    leader = max(valid, key=lambda m: m.delta if m.delta is not None else float("-inf"))
    others = [m for m in valid if m.board_code != leader.board_code]
    k = theme.trend_k
    days = window_days if window_days is not None else theme.window_trading_days
    leader_slope = warming_slope_from_heats(
        heat_by_code.get(leader.board_code, ()), k=k
    )
    word = _trend_word(
        leader_slope,
        epsilon_slope=theme.epsilon_slope,
        window_delta=leader.delta,
        window_days=days,
    )
    other_slopes = [
        warming_slope_from_heats(heat_by_code.get(m.board_code, ()), k=k)
        for m in others
    ]
    others_phrase = _others_trend_phrase(other_slopes, theme.epsilon_slope)
    if word is None:
        if all(slope is None for slope in other_slopes):
            return f"{detail}；近{k}日趋势不足"
        return f"{detail}；近{k}日{leader.board_name}近端不足，{others_phrase}"
    return f"{detail}；近{k}日{leader.board_name}{word}，{others_phrase}"


def judge_group_a(
    members: Sequence[MemberWindow],
    theme: ThemeConfig,
    *,
    heat_by_code: Mapping[str, Sequence[float | None]] | None = None,
    window_days: int | None = None,
) -> GroupBadge:
    valid = [m for m in members if m.sign is not None and m.delta is not None]
    if len(valid) < 2:
        return GroupBadge("数据不足", "有效成员不足 2 个", None)

    deltas = [m.delta for m in valid if m.delta is not None]
    spread0 = _spread([m.pct_d0 for m in valid])
    spread1 = _spread([m.pct_as_of for m in valid])
    delta_spread = (
        None if spread0 is None or spread1 is None else spread1 - spread0
    )
    group_delta = group_median(deltas)

    near_slopes = (
        _member_near_slopes(valid, heat_by_code, theme) if heat_by_code else {}
    )
    near_signs = {
        code: sign_from_warming_slope(slope, theme.epsilon_slope)
        for code, slope in near_slopes.items()
    }
    use_near = bool(near_signs) and all(
        near_signs.get(m.board_code) is not None for m in valid
    )

    if use_near:
        signs = {m.board_code: near_signs[m.board_code] for m in valid}
        leader = max(
            valid,
            key=lambda m: (
                near_slopes.get(m.board_code)
                if near_slopes.get(m.board_code) is not None
                else float("-inf")
            ),
        )
    else:
        signs = {m.board_code: m.sign for m in valid}
        leader = max(
            valid, key=lambda m: m.delta if m.delta is not None else float("-inf")
        )

    others = [m for m in valid if m.board_code != leader.board_code]
    n_hot = sum(1 for m in valid if signs.get(m.board_code) == SIGN_HOT)
    n_cold = sum(1 for m in valid if signs.get(m.board_code) == SIGN_COLD)
    co_move = max(n_hot, n_cold) / len(valid)

    def _window_contrast() -> str:
        if not use_near or group_delta is None:
            return ""
        window_sign = sign_delta(group_delta, theme.epsilon)
        if window_sign == SIGN_COLD and n_hot >= 2 and n_cold == 0:
            return "（整窗净变化仍偏冷）"
        if window_sign == SIGN_HOT and n_cold >= 2 and n_hot == 0:
            return "（整窗净变化仍偏热）"
        return ""

    def _badge(label: str, detail: str) -> GroupBadge:
        return GroupBadge(
            label,
            _append_recent_trend(detail, members, theme, heat_by_code, window_days),
            group_delta,
            spread0,
            spread1,
            co_move,
        )

    # 仅龙头热：近端用斜率领涨+其余走平；否则退回整窗 Δ 规则。
    if use_near:
        leader_slope = near_slopes.get(leader.board_code)
        others_flat = others and all(
            signs.get(m.board_code) == SIGN_FLAT for m in others
        )
        if (
            leader_slope is not None
            and signs.get(leader.board_code) == SIGN_HOT
            and others_flat
        ):
            return _badge(
                "仅龙头热",
                f"{leader.board_name} 近端升温，其余未跟上{_window_contrast()}",
            )
    elif (
        leader.delta is not None
        and leader.delta >= theme.lambda_lead
        and others
        and all(m.delta is not None and m.delta <= theme.epsilon for m in others)
    ):
        return _badge(
            "仅龙头热",
            f"{leader.board_name} 窗口变热 {leader.delta:.1f}，其余未跟上",
        )

    if (n_hot >= 1 and n_cold >= 1) or (
        delta_spread is not None and delta_spread >= theme.sigma_spread
    ):
        scope = "近端" if use_near else "窗口"
        if n_hot and n_cold:
            detail = f"成员{scope}方向对立"
        elif n_hot >= 2 and n_cold == 0:
            detail = f"均在变热，但成员分位离散明显拉大{_window_contrast()}"
        elif n_cold >= 2 and n_hot == 0:
            detail = f"均在变冷，但成员分位离散明显拉大{_window_contrast()}"
        else:
            detail = "分位离散明显拉大"
        return _badge("拆开", detail)

    if n_hot >= 2 and n_cold == 0:
        scope = "近端" if use_near else "窗口"
        return _badge(
            "同热",
            f"{n_hot}/{len(valid)} 成员{scope}变热{_window_contrast()}",
        )

    if n_cold >= 2 and n_hot == 0:
        scope = "近端" if use_near else "窗口"
        return _badge(
            "同冷",
            f"{n_cold}/{len(valid)} 成员{scope}变冷{_window_contrast()}",
        )

    return _badge("平稳", "多数落在平坦带")


def short_group_label(label: str) -> str:
    if "·" in label:
        return label.split("·", 1)[1].strip()
    return label


def judge_pair(
    delta_a: float | None,
    delta_b: float | None,
    pct_a_d0: float | None,
    pct_a_as_of: float | None,
    pct_b_d0: float | None,
    pct_b_as_of: float | None,
    theme: ThemeConfig,
    *,
    near_sign_a: int | None = None,
    near_sign_b: int | None = None,
) -> PairBadge:
    if delta_a is None or delta_b is None:
        return PairBadge("数据不足", None, "群热度窗口不完整", None, None, None, None)

    window_s_a = sign_delta(delta_a, theme.epsilon)
    window_s_b = sign_delta(delta_b, theme.epsilon)
    use_near = near_sign_a is not None and near_sign_b is not None
    s_a = near_sign_a if use_near else window_s_a
    s_b = near_sign_b if use_near else window_s_b
    gap0 = (
        None
        if pct_a_d0 is None or pct_b_d0 is None
        else abs(pct_a_d0 - pct_b_d0)
    )
    gap1 = (
        None
        if pct_a_as_of is None or pct_b_as_of is None
        else abs(pct_a_as_of - pct_b_as_of)
    )
    delta_gap = None if gap0 is None or gap1 is None else gap1 - gap0
    name_a = short_group_label(theme.group_a_label)
    name_b = short_group_label(theme.group_b_label)

    def _pair_contrast(direction: str) -> str:
        if not use_near:
            return direction
        if (
            direction == "同热"
            and window_s_a == SIGN_COLD
            and window_s_b == SIGN_COLD
        ):
            return "同热（整窗仍同冷）"
        if (
            direction == "同冷"
            and window_s_a == SIGN_HOT
            and window_s_b == SIGN_HOT
        ):
            return "同冷（整窗仍同热）"
        return direction

    if s_a == SIGN_HOT and s_b == SIGN_COLD:
        return PairBadge(
            "A热B冷",
            None,
            f"{name_a}变热，{name_b}变冷",
            delta_a,
            delta_b,
            gap0,
            gap1,
        )
    if s_a == SIGN_COLD and s_b == SIGN_HOT:
        return PairBadge(
            "A冷B热",
            None,
            f"{name_a}变冷，{name_b}变热",
            delta_a,
            delta_b,
            gap0,
            gap1,
        )

    if delta_gap is not None and delta_gap >= theme.gamma_gap and not (
        s_a == s_b and s_a != SIGN_FLAT
    ):
        return PairBadge(
            "分叉",
            None,
            f"群间分位缺口扩大 {delta_gap:.2f}",
            delta_a,
            delta_b,
            gap0,
            gap1,
        )

    if s_a == s_b and s_a != SIGN_FLAT:
        sub = None
        if delta_gap is not None and delta_gap >= theme.gamma_gap:
            sub = "缺口扩大"
        elif delta_gap is not None and delta_gap <= -theme.gamma_gap:
            sub = "缺口收敛"
        direction = "同热" if s_a == SIGN_HOT else "同冷"
        return PairBadge(
            "同向",
            sub,
            _pair_contrast(direction),
            delta_a,
            delta_b,
            gap0,
            gap1,
        )

    return PairBadge(
        "弱联动",
        None,
        "至少一侧平坦，且缺口未明显拉大",
        delta_a,
        delta_b,
        gap0,
        gap1,
    )


def judge_satellite(
    board_code: str,
    board_name: str,
    heat_d0: float | None,
    heat_as_of: float | None,
    pct_as_of: float | None,
    domain_deltas: Sequence[float | None],
    theme: ThemeConfig,
    group_a_label: str,
) -> SatelliteBadge:
    delta = window_delta(heat_d0, heat_as_of)
    if delta is None or pct_as_of is None:
        return SatelliteBadge(
            board_code,
            board_name,
            "数据不足",
            "窗口热度不完整",
            delta,
            pct_as_of,
        )

    ref = group_median(list(domain_deltas))
    burst = pct_as_of <= theme.satellite_percentile or (
        delta >= theme.lambda_sat
        and ref is not None
        and delta >= ref + theme.mu_sat
    )
    if burst:
        return SatelliteBadge(
            board_code,
            board_name,
            "爆发中",
            f"此时群A为「{group_a_label}」",
            delta,
            pct_as_of,
        )
    return SatelliteBadge(
        board_code,
        board_name,
        "安静",
        "未触发爆发门槛",
        delta,
        pct_as_of,
    )


def daily_group_median_series(
    dates: Sequence[date],
    member_codes: Sequence[str],
    heat_by_day: Mapping[date, Mapping[str, float]],
    use_percentile: bool,
    pct_by_day: Mapping[date, Mapping[str, float]] | None = None,
) -> list[tuple[date, float | None]]:
    series: list[tuple[date, float | None]] = []
    for day in dates:
        if use_percentile:
            source = (pct_by_day or {}).get(day, {})
            values = [source.get(code) for code in member_codes]
        else:
            source = heat_by_day.get(day, {})
            values = [source.get(code) for code in member_codes]
        series.append((day, group_median(values)))
    return series
