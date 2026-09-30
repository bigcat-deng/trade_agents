"""Static theme membership and badge thresholds."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeBoard:
    board_code: str
    board_name: str


@dataclass(frozen=True)
class ThemeConfig:
    theme_id: str
    title: str
    board_type: str
    group_a: tuple[ThemeBoard, ...]
    group_b: tuple[ThemeBoard, ...]
    satellites: tuple[ThemeBoard, ...]
    group_a_label: str = "群A"
    group_b_label: str = "群B"
    satellite_label: str = "卫星"
    group_a_reason: str = ""
    group_b_reason: str = ""
    satellite_reason: str = ""
    grouping_note: str = ""
    interpret_template: str = ""
    window_trading_days: int = 20
    # Window Δ flat band (heat_short rank units).
    epsilon: float = 5.0
    # Leader-only heat: Δ_lead >= lambda_lead and others Δ <= epsilon.
    lambda_lead: float = 15.0
    # Group A percentile spread widen threshold.
    sigma_spread: float = 0.15
    # A–B gap widen threshold (percentile).
    gamma_gap: float = 0.12
    # Satellite burst: percentile at as_of (0=hottest).
    satellite_percentile: float = 0.10
    # Satellite burst: Δ and excess over domain median Δ.
    lambda_sat: float = 15.0
    mu_sat: float = 10.0
    # Recent heat_short OLS window (trading days) for badge trend suffix.
    trend_k: int = 5
    # |warming slope| (rank units / day) flat band; >0 means getting hotter.
    epsilon_slope: float = 0.5


def theme_board_codes(theme: ThemeConfig) -> list[str]:
    codes = [board.board_code for board in theme.group_a]
    codes.extend(board.board_code for board in theme.group_b)
    codes.extend(board.board_code for board in theme.satellites)
    return codes


def constants_footnote(theme: ThemeConfig) -> list[tuple[str, str]]:
    return [
        ("窗口", f"{theme.window_trading_days} 个交易日"),
        ("ε 平坦带", str(theme.epsilon)),
        ("λ 龙头变热", str(theme.lambda_lead)),
        ("σ A 内离散拉大", str(theme.sigma_spread)),
        ("γ A–B 缺口拉大", str(theme.gamma_gap)),
        ("卫星分位爆发", f"≤ {theme.satellite_percentile}"),
        ("λ_sat / μ", f"{theme.lambda_sat} / {theme.mu_sat}"),
        ("近端拟合", f"{theme.trend_k} 日"),
        ("ε_slope 近端平坦", str(theme.epsilon_slope)),
        ("徽章同热/同冷", "近端斜率优先"),
    ]
