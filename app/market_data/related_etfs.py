"""Name-based board ↔ ETF suggestions (MVP, not an official mapping)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date

from app.charts.chan_board import WINDOW, chan_fetch_start, drawn_key_levels
from app.levels.target_stop import target_stop_plan
from app.market_data.codes import to_akshare_em
from app.market_data.etf_scale import fetch_etf_share_map, format_aum_yi
from app.market_data.providers.ths_line import fetch_ths_daily_bars
from scripts.chan_fractal_probe import prepare_chan_window

# Extra search terms when the board name alone misses themed ETFs.
# Keys are exact board_universe names (or common stems we normalize to).
BOARD_ETF_ALIASES: dict[str, tuple[str, ...]] = {
    "猪肉": ("畜牧养殖", "生猪"),
    "养鸡": ("畜牧养殖", "禽畜"),
    "养殖业": ("畜牧养殖", "生猪"),
    "半导体": ("芯片", "集成电路"),
    "软件开发": ("软件", "信创"),
    "证券": ("券商",),
    "保险": ("非银",),
    "白酒": ("酒",),
    "小金属": ("有色", "稀有金属"),
    "贵金属": ("黄金",),
    "煤炭开采加工": ("煤炭",),
    "油气开采及服务": ("油气", "石油"),
    "石油加工贸易": ("石化", "炼化"),
    "机场航运": ("航空", "机场"),
    "港口航运": ("港口", "航运"),
    "旅游及酒店": ("旅游", "酒店"),
    "文化传媒": ("传媒", "影视"),
    "电池": ("锂电", "新能源车"),
    "光伏设备": ("光伏",),
    "风电设备": ("风电",),
    "电网设备": ("电力", "特高压"),
    "电机": ("机器人",),
}

_CANDIDATE_LIMIT = 40
_DEFAULT_LIMIT = 12
_PROBE_WORKERS = 6


@dataclass(frozen=True)
class RelatedEtf:
    code: str
    name: str
    matched: str
    score: int


@dataclass(frozen=True)
class RelatedEtfRow:
    code: str
    name: str
    matched: str
    score: int
    ths_code: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    yield_rate: float | None
    chan_ratio: float | None
    shares: float | None


def _normalize_board_name(name: str) -> str:
    value = (name or "").strip()
    for suffix in ("概念", "板块", "Ⅱ", "Ⅲ", "II", "III"):
        if value.endswith(suffix) and len(value) > len(suffix):
            value = value[: -len(suffix)]
    return value.strip()


def keywords_for_board(board_name: str) -> list[str]:
    """Ordered search terms: exact name first, then aliases / stem."""
    raw = (board_name or "").strip()
    stem = _normalize_board_name(raw)
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(term: str) -> None:
        key = term.strip()
        if len(key) < 2 or key in seen:
            return
        seen.add(key)
        ordered.append(key)

    _add(raw)
    _add(stem)
    for source in (raw, stem):
        for alias in BOARD_ETF_ALIASES.get(source, ()):
            _add(alias)
    return ordered


def _match_score(etf_name: str, keywords: list[str]) -> tuple[int, str] | None:
    """Higher is better. Prefer earlier (more specific) keywords and longer hits."""
    best: tuple[int, str] | None = None
    for index, key in enumerate(keywords):
        if key not in etf_name:
            continue
        score = 1000 - index * 50 + len(key) * 10
        if best is None or score > best[0]:
            best = (score, key)
    return best


def find_related_etfs(
    board_name: str,
    universe: list[tuple[str, str]],
    *,
    limit: int = _DEFAULT_LIMIT,
) -> list[RelatedEtf]:
    """Pick ETFs whose names contain the board name or an alias."""
    keywords = keywords_for_board(board_name)
    if not keywords or limit <= 0:
        return []

    hits: list[RelatedEtf] = []
    for code, name in universe:
        name = (name or "").strip()
        code = (code or "").strip()
        if not code or not name or "ETF" not in name.upper():
            continue
        matched = _match_score(name, keywords)
        if matched is None:
            continue
        score, key = matched
        hits.append(RelatedEtf(code=code, name=name, matched=key, score=score))

    hits.sort(key=lambda row: (-row.score, row.code))
    return hits[:limit]


def build_related_etf_rows(
    board_name: str,
    universe: list[tuple[str, str]],
    *,
    as_of: date,
    limit: int = _DEFAULT_LIMIT,
    share_map: dict[str, float] | None = None,
) -> list[RelatedEtfRow]:
    """Name-match, keep only codes Tonghuashun can chart, attach OHLC / yields / AUM."""
    candidates = find_related_etfs(
        board_name,
        universe,
        limit=max(limit, _CANDIDATE_LIMIT),
    )
    if not candidates:
        return []
    shares = share_map if share_map is not None else fetch_etf_share_map()
    fetch_start = chan_fetch_start(as_of)
    rows: list[RelatedEtfRow | None] = [None] * len(candidates)

    def _one(index: int, hit: RelatedEtf) -> tuple[int, RelatedEtfRow | None]:
        try:
            ths = to_akshare_em(hit.code)
        except ValueError:
            return index, None
        try:
            bars = fetch_ths_daily_bars(ths, fetch_start, as_of)
        except (RuntimeError, ValueError):
            return index, None
        if not bars:
            return index, None
        last = bars[-1]
        close = float(last["close"])
        return index, RelatedEtfRow(
            code=hit.code,
            name=hit.name,
            matched=hit.matched,
            score=hit.score,
            ths_code=ths,
            trade_date=last["trade_date"],
            open=float(last["open"]),
            high=float(last["high"]),
            low=float(last["low"]),
            close=close,
            yield_rate=_daily_yield_rate(bars),
            chan_ratio=_chan_reward_risk_ratio(bars),
            shares=shares.get(ths),
        )

    workers = min(_PROBE_WORKERS, len(candidates))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_one, index, hit) for index, hit in enumerate(candidates)
        ]
        for fut in as_completed(futures):
            index, row = fut.result()
            rows[index] = row

    kept = [row for row in rows if row is not None]
    kept.sort(key=_yield_sort_key)
    return kept[:limit]


def _yield_sort_key(row: RelatedEtfRow) -> tuple:
    """Higher daily return first; missing yields sink to the bottom."""
    return (row.yield_rate is None, -(row.yield_rate or 0.0), row.code)


def related_etf_view(row: RelatedEtfRow, analyze_href: str) -> dict[str, str]:
    return {
        "code": row.ths_code,
        "name": row.name,
        "matched": row.matched,
        "analyze_href": analyze_href,
        "scale_text": format_aum_yi(row.shares, row.close),
        "trade_date": row.trade_date.isoformat(),
        "open_text": _price_text(row.open),
        "high_text": _price_text(row.high),
        "low_text": _price_text(row.low),
        "close_text": _price_text(row.close),
        "yield_text": _percent_text(row.yield_rate),
        "chan_ratio_text": _ratio_text(row.chan_ratio),
    }


def _daily_yield_rate(bars: list[dict]) -> float | None:
    """Close vs previous close on the tip bar."""
    if len(bars) < 2:
        return None
    close = float(bars[-1]["close"])
    prev = float(bars[-2]["close"])
    if prev == 0:
        return None
    return (close - prev) / prev


def _chan_reward_risk_ratio(bars: list[dict]) -> float | None:
    """Target reward : stop risk as x in ``x : 1``, same as analyze / members."""
    if len(bars) < 2:
        return None
    window = prepare_chan_window(bars, n=WINDOW)
    close = float(window.closes[-1])
    try:
        keys = drawn_key_levels(window)
        plan = target_stop_plan(
            [level.price for level in keys],
            high=float(window.highs[-1]),
            low=float(window.lows[-1]),
            close=close,
        )
    except ValueError:
        return None
    if plan.mode == "outside" or plan.ratio is None:
        return None
    return float(plan.ratio)


def _price_text(value: float) -> str:
    if value >= 100:
        return f"{value:.2f}"
    if value >= 10:
        return f"{value:.3f}"
    return f"{value:.3f}"


def _percent_text(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.2f}%"


def _ratio_text(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2f} : 1"
