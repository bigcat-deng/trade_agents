"""Eastmoney industry/concept board providers.

Universe list is fetched via a probe chain: try methods in order with a short
timeout; on failure, switch to the next method.
"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import date
from typing import Any, Callable, Literal
from urllib.parse import urlencode

import akshare as ak

from app.market_data.board_cache import load_json, save_json
from app.market_data.normalize import (
    BoardDailyBar,
    BoardUniverseRow,
    BoardConstituentRow,
    from_akshare_em_board_hist_row,
    from_akshare_em_board_name_row,
    from_akshare_em_board_cons_row,
)

BoardType = Literal["industry", "concept"]
SOURCE = "akshare_em"

_PERIOD_BY_TYPE: dict[BoardType, str] = {
    "industry": "日k",
    "concept": "daily",
}

_CLIST_HOSTS = (
    "push2.eastmoney.com",
    "79.push2.eastmoney.com",
    "17.push2.eastmoney.com",
)

_KLINE_HOSTS = (
    "push2his.eastmoney.com",
    "7.push2his.eastmoney.com",
    "91.push2his.eastmoney.com",
)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/center/boardlist.html",
    "Accept": "*/*",
}

_FS_BY_TYPE: dict[BoardType, str] = {
    "industry": "m:90 t:2 f:!50",
    "concept": "m:90 t:3 f:!50",
}

# Remember which universe / kline method worked last in this process.
_last_good_universe_source: str | None = None
_last_good_kline_source: str | None = None

PROBE_TIMEOUT_SEC = 4.0
FETCH_TIMEOUT_SEC = 25.0
LAST_RESORT_TIMEOUT_SEC = 90.0
NETWORK_RETRIES = 4


def _retry(label: str, fn: Callable[[], Any], *, retries: int = NETWORK_RETRIES) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - network boundary
            last_error = exc
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 8))
    raise RuntimeError(f"{label} failed after {retries} tries: {last_error}")


class BoardUniverseFetchInfo:
    """Result metadata so the job can log which source succeeded."""

    def __init__(
        self,
        rows: list[BoardUniverseRow],
        source: str,
        note: str = "",
        attempts: list[str] | None = None,
    ):
        self.rows = rows
        self.source = source
        self.note = note
        self.attempts = attempts or []


def _http_get_json(url: str, *, timeout: float = 20.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_clist_page(
    board_type: BoardType,
    page: int,
    *,
    page_size: int = 100,
    timeout: float = PROBE_TIMEOUT_SEC,
    hosts: tuple[str, ...] | None = None,
) -> tuple[list[dict], int]:
    params = {
        "pn": str(page),
        "pz": str(page_size),
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3" if board_type == "industry" else "f12",
        "fs": _FS_BY_TYPE[board_type],
        "fields": "f12,f14",
    }
    query = urlencode(params)
    errors: list[str] = []
    for host in hosts or _CLIST_HOSTS[:2]:
        url = f"https://{host}/api/qt/clist/get?{query}"
        try:
            data = _http_get_json(url, timeout=timeout)
            payload = data.get("data") or {}
            diff = payload.get("diff") or []
            total = int(payload.get("total") or 0)
            return diff, total
        except Exception as exc:  # noqa: BLE001 - host rotation
            errors.append(f"{host}: {exc}")
    raise RuntimeError("clist failed; " + "; ".join(errors[:2]))


def _rows_from_clist_diff(
    trade_date: date, board_type: BoardType, diff: list[dict]
) -> list[BoardUniverseRow]:
    rows: list[BoardUniverseRow] = []
    for item in diff:
        code = str(item.get("f12") or "").strip().upper()
        name = str(item.get("f14") or "").strip()
        if not code or not name:
            continue
        rows.append(
            BoardUniverseRow(
                trade_date=trade_date,
                board_type=board_type,
                board_code=code,
                board_name=name,
                source=SOURCE,
            )
        )
    return rows


def _fetch_via_clist(
    trade_date: date,
    board_type: BoardType | None,
    *,
    timeout: float = FETCH_TIMEOUT_SEC,
) -> list[BoardUniverseRow]:
    types: tuple[BoardType, ...]
    if board_type is None:
        types = ("industry", "concept")
    else:
        types = (board_type,)

    rows: list[BoardUniverseRow] = []
    for btype in types:
        page = 1
        while True:
            diff, total = _fetch_clist_page(btype, page, timeout=min(timeout, 8.0))
            if not diff:
                break
            rows.extend(_rows_from_clist_diff(trade_date, btype, diff))
            if total is not None and sum(1 for r in rows if r.board_type == btype) >= total:
                break
            if len(diff) < 100:
                break
            page += 1
            if page > 50:
                break
            time.sleep(0.1)
    if board_type is None and {r.board_type for r in rows} < {"industry", "concept"}:
        raise RuntimeError("clist returned incomplete industry/concept coverage")
    if not rows:
        raise RuntimeError("clist returned no boards")
    return rows


def _probe_clist() -> None:
    diff, _total = _fetch_clist_page("industry", 1, page_size=5, timeout=PROBE_TIMEOUT_SEC)
    if not diff:
        raise RuntimeError("clist probe empty")


def _fetch_via_akshare(
    trade_date: date,
    board_type: BoardType | None,
) -> list[BoardUniverseRow]:
    types: tuple[BoardType, ...]
    if board_type is None:
        types = ("industry", "concept")
    else:
        types = (board_type,)

    rows: list[BoardUniverseRow] = []
    for btype in types:
        if btype == "industry":
            frame = ak.stock_board_industry_name_em()
        else:
            frame = ak.stock_board_concept_name_em()
        if frame is None or frame.empty:
            raise RuntimeError(f"akshare {btype} empty")
        for _, raw in frame.iterrows():
            try:
                rows.append(
                    from_akshare_em_board_name_row(
                        raw.to_dict(),
                        trade_date=trade_date,
                        board_type=btype,
                    )
                )
            except (KeyError, ValueError):
                continue
    if board_type is None and {r.board_type for r in rows} < {"industry", "concept"}:
        raise RuntimeError("akshare returned incomplete industry/concept coverage")
    if not rows:
        raise RuntimeError("akshare returned no boards")
    return rows


def _probe_akshare() -> None:
    frame = ak.stock_board_industry_name_em()
    if frame is None or frame.empty:
        raise RuntimeError("akshare probe empty")


def _fetch_bk_changes(*, timeout: float = FETCH_TIMEOUT_SEC) -> list[tuple[str, str]]:
    params = urlencode(
        {
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "dpt": "wzchanges",
            "pageindex": "0",
            "pagesize": "5000",
        }
    )
    url = f"https://push2ex.eastmoney.com/getAllBKChanges?{params}"

    def _once() -> list[tuple[str, str]]:
        data = _http_get_json(url, timeout=timeout)
        items = ((data.get("data") or {}).get("allbk")) or []
        rows: list[tuple[str, str]] = []
        for item in items:
            code = str(item.get("c") or "").strip().upper()
            name = str(item.get("n") or "").strip()
            if code.startswith("BK") and name:
                rows.append((code, name))
        if not rows:
            raise RuntimeError("getAllBKChanges returned no boards")
        return rows

    try:
        rows = _retry("getAllBKChanges", _once)
        save_json(
            "bk_changes_boards.json",
            [{"code": code, "name": name} for code, name in rows],
        )
        return rows
    except Exception as exc:
        cached = load_json("bk_changes_boards.json")
        if isinstance(cached, list) and cached:
            rows = [
                (str(item["code"]).upper(), str(item["name"]))
                for item in cached
                if item.get("code") and item.get("name")
            ]
            if rows:
                return rows
        raise RuntimeError(f"getAllBKChanges failed and no cache: {exc}") from exc


def _normalize_board_name(name: str) -> str:
    return name.replace("Ⅱ", "").replace("Ⅲ", "").replace("II", "").replace("III", "").strip()


# Map fund-flow / THS-style industry titles onto Eastmoney board names.
_INDUSTRY_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "公路铁路运输": ("铁路公路", "高速公路", "公路货运"),
    "其他社会服务": ("专业服务", "其他专业服务"),
    "军工装备": ("国防军工", "军工"),
    "塑料制品": ("塑料", "其他塑料制品"),
    "文化传媒": ("传媒",),
    "旅游及酒店": ("旅游酒店", "酒店餐饮", "旅游综合"),
    "机场航运": ("航空机场", "机场"),
    "橡胶制品": ("橡胶", "其他橡胶制品"),
    "汽车服务及其他": ("汽车服务",),
    "油气开采及服务": ("油气开采",),
    "港口航运": ("航运港口", "港口", "航运"),
    "煤炭开采加工": ("煤炭开采", "煤炭"),
    "石油加工贸易": ("油品石化贸易", "炼化及贸易", "石油石化"),
    "种植业与林业": ("种植业", "林业Ⅱ", "农业种植"),
    "零售": ("一般零售", "商贸零售", "多业态零售"),
    "食品加工制造": ("食品加工",),
    "饮料制造": ("饮料乳品", "软饮料"),
}


def _reference_industry_names() -> list[str]:
    def _once() -> list[str]:
        frame = ak.stock_fund_flow_industry()
        if frame is None or frame.empty or "行业" not in frame.columns:
            raise RuntimeError("stock_fund_flow_industry empty")
        names = [str(name).strip() for name in frame["行业"].tolist() if str(name).strip()]
        if len(names) < 50:
            raise RuntimeError(f"industry reference too small: {len(names)}")
        return names

    try:
        names = _retry("stock_fund_flow_industry", _once)
        save_json("industry_names.json", names)
        return names
    except Exception as exc:
        cached = load_json("industry_names.json")
        if isinstance(cached, list) and len(cached) >= 50:
            return [str(name) for name in cached]
        raise RuntimeError(f"industry reference failed and no cache: {exc}") from exc


def _reference_concept_names() -> list[str]:
    def _once() -> list[str]:
        frame = ak.stock_fund_flow_concept()
        if frame is None or frame.empty or "行业" not in frame.columns:
            raise RuntimeError("stock_fund_flow_concept empty")
        names = [str(name).strip() for name in frame["行业"].tolist() if str(name).strip()]
        if len(names) < 100:
            raise RuntimeError(f"concept reference too small: {len(names)}")
        return names

    try:
        names = _retry("stock_fund_flow_concept", _once, retries=3)
        save_json("concept_names.json", names)
        return names
    except Exception as exc:
        cached = load_json("concept_names.json")
        if isinstance(cached, list) and len(cached) >= 100:
            return [str(name) for name in cached]
        raise RuntimeError(f"concept reference failed and no cache: {exc}") from exc


def _pick_em_name(
    target: str,
    em_by_name: dict[str, str],
    *,
    aliases: tuple[str, ...] = (),
    allow_concept: bool = False,
) -> str | None:
    options = (target, *aliases)
    for option in options:
        if option in em_by_name and (allow_concept or "概念" not in option):
            return option

    candidates: list[str] = []
    for option in options:
        opt_norm = _normalize_board_name(option)
        for name in em_by_name:
            if not allow_concept and "概念" in name:
                continue
            if name == option or _normalize_board_name(name) == opt_norm:
                candidates.append(name)
            elif name.startswith(option + "Ⅱ") or name.startswith(option + "Ⅲ"):
                candidates.append(name)
    if not candidates:
        return None
    candidates = sorted(
        set(candidates),
        key=lambda name: (
            0 if name.endswith("Ⅱ") else 1 if _normalize_board_name(name) == _normalize_board_name(target) else 2,
            len(name),
        ),
    )
    return candidates[0]


def _classify_bk_changes(
    boards: list[tuple[str, str]],
    prior_types: dict[str, str],
) -> tuple[dict[str, BoardType], dict[str, int]]:
    """Return code->type for industry/concept only; drop style/region boards."""
    em_by_name = {name: code for code, name in boards}
    code_types: dict[str, BoardType] = {}
    warnings: list[str] = []

    try:
        industry_names = _reference_industry_names()
        for industry in industry_names:
            aliases = _INDUSTRY_NAME_ALIASES.get(industry, ())
            hit = _pick_em_name(
                industry, em_by_name, aliases=aliases, allow_concept=False
            )
            if hit is None:
                continue
            code_types[em_by_name[hit]] = "industry"
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"industry_ref:{exc}")
        cached_map = load_json("code_types.json")
        if isinstance(cached_map, dict):
            for code, board_type in cached_map.items():
                if board_type == "industry":
                    code_types[str(code).upper()] = "industry"

    try:
        concept_names = _reference_concept_names()
        for concept in concept_names:
            hit = _pick_em_name(concept, em_by_name, allow_concept=True)
            if hit is None:
                continue
            code = em_by_name[hit]
            if code in code_types:
                continue
            code_types[code] = "concept"
    except Exception as exc:  # noqa: BLE001 - concept map is best-effort
        warnings.append(f"concept_ref:{exc}")
        cached_map = load_json("code_types.json")
        if isinstance(cached_map, dict):
            for code, board_type in cached_map.items():
                code = str(code).upper()
                if code in code_types:
                    continue
                if board_type == "concept":
                    code_types[code] = "concept"
        # Last fallback: names containing 概念.
        for code, name in boards:
            if code in code_types:
                continue
            if "概念" in name:
                code_types[code] = "concept"

    for code, prior in prior_types.items():
        if code not in code_types and prior in {"industry", "concept"}:
            code_types[code] = prior  # type: ignore[assignment]

    # Keep only codes that still exist in today's board list.
    alive = {code for code, _name in boards}
    code_types = {
        code: board_type
        for code, board_type in code_types.items()
        if code in alive and board_type in {"industry", "concept"}
    }

    if len(code_types) >= 100:
        save_json("code_types.json", code_types)

    stats = {
        "raw": len(boards),
        "industry": sum(1 for value in code_types.values() if value == "industry"),
        "concept": sum(1 for value in code_types.values() if value == "concept"),
        "dropped": len(boards) - len(code_types),
        "warnings": "; ".join(warnings),
    }
    return code_types, stats


def _fetch_via_bk_changes(
    trade_date: date,
    board_type: BoardType | None,
    prior_types: dict[str, str],
) -> list[BoardUniverseRow]:
    boards = _fetch_bk_changes()
    code_types, stats = _classify_bk_changes(boards, prior_types)
    name_by_code = {code: name for code, name in boards}

    rows: list[BoardUniverseRow] = []
    for code, resolved in sorted(code_types.items()):
        if board_type is not None and resolved != board_type:
            continue
        name = name_by_code.get(code)
        if not name:
            continue
        rows.append(
            BoardUniverseRow(
                trade_date=trade_date,
                board_type=resolved,
                board_code=code,
                board_name=name,
                source=SOURCE,
            )
        )
    if not rows:
        raise RuntimeError(
            "bk_changes produced no classified industry/concept rows; "
            f"stats={stats}"
        )
    # Stash stats on function attribute for the job note.
    _fetch_via_bk_changes.last_stats = stats  # type: ignore[attr-defined]
    return rows


def _probe_bk_changes() -> None:
    rows = _fetch_bk_changes(timeout=PROBE_TIMEOUT_SEC)
    if not rows:
        raise RuntimeError("bk_changes probe empty")


def _universe_methods(
    trade_date: date,
    board_type: BoardType | None,
    prior_types: dict[str, str],
) -> list[tuple[str, Callable[[], None], Callable[[], list[BoardUniverseRow]], str]]:
    """(name, probe, fetch, note_if_used)."""
    # akshare *_name_em is omitted: it hits the same fragile push2 clist CDN and can hang.
    return [
        (
            "clist",
            _probe_clist,
            lambda: _fetch_via_clist(trade_date, board_type),
            "official Eastmoney industry/concept split",
        ),
        (
            "bk_changes",
            _probe_bk_changes,
            lambda: _fetch_via_bk_changes(trade_date, board_type, prior_types),
            (
                "push2ex getAllBKChanges classified via fund-flow industry/concept "
                "name maps; unmatched style/region boards dropped"
            ),
        ),
    ]


def _ordered_methods(
    trade_date: date,
    board_type: BoardType | None,
    prior_types: dict[str, str],
) -> list[tuple[str, Callable[[], None], Callable[[], list[BoardUniverseRow]], str]]:
    methods = _universe_methods(trade_date, board_type, prior_types)
    global _last_good_universe_source
    if _last_good_universe_source:
        methods.sort(key=lambda item: 0 if item[0] == _last_good_universe_source else 1)
    return methods


def fetch_board_universe(
    trade_date: date,
    board_type: BoardType,
    *,
    prior_types: dict[str, str] | None = None,
) -> list[BoardUniverseRow]:
    info = fetch_all_board_universe(
        trade_date,
        board_type=board_type,
        prior_types=prior_types,
    )
    return info.rows


def fetch_all_board_universe(
    trade_date: date,
    *,
    board_type: BoardType | None = None,
    prior_types: dict[str, str] | None = None,
) -> BoardUniverseFetchInfo:
    """Probe download methods in order; use the first that works."""
    global _last_good_universe_source
    prior = prior_types or {}
    attempts: list[str] = []
    methods = _ordered_methods(trade_date, board_type, prior)

    for index, (name, probe, fetch, note) in enumerate(methods):
        is_last = index == len(methods) - 1
        if not is_last:
            try:
                probe()
            except Exception as exc:  # noqa: BLE001 - probe boundary
                attempts.append(f"{name}: probe fail ({exc})")
                continue
        else:
            attempts.append(f"{name}: skip probe (last resort)")

        try:
            rows = fetch()
        except Exception as exc:  # noqa: BLE001 - fetch boundary
            attempts.append(f"{name}: fetch fail ({exc})")
            continue

        if not rows:
            attempts.append(f"{name}: fetch empty")
            continue

        _last_good_universe_source = name
        extra = ""
        stats = getattr(_fetch_via_bk_changes, "last_stats", None)
        if name == "bk_changes" and isinstance(stats, dict):
            extra = (
                f", classified industry={stats.get('industry')} "
                f"concept={stats.get('concept')} dropped={stats.get('dropped')}"
            )
        attempts.append(f"{name}: ok ({len(rows)} rows{extra})")
        note_text = note
        if name == "bk_changes" and isinstance(stats, dict):
            note_text = (
                f"{note}; raw={stats.get('raw')} kept={len(rows)} "
                f"dropped={stats.get('dropped')}"
            )
        return BoardUniverseFetchInfo(
            rows,
            source=name,
            note=note_text,
            attempts=attempts,
        )

    raise RuntimeError(
        "all board universe sources failed; " + " | ".join(attempts)
    )


def _fetch_kline_raw(board_code: str, start: date, end: date) -> list[str]:
    params = {
        "secid": f"90.{board_code}",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "0",
        "beg": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
        "smplmt": "10000",
        "lmt": "1000000",
    }
    query = urlencode(params)
    errors: list[str] = []
    for scheme in ("http", "https"):
        for host in _KLINE_HOSTS:
            url = f"{scheme}://{host}/api/qt/stock/kline/get?{query}"

            def _once(url: str = url) -> list[str]:
                data = _http_get_json(url, timeout=20)
                payload = data.get("data") or {}
                klines = payload.get("klines") or []
                if not isinstance(klines, list):
                    raise RuntimeError("klines field is not a list")
                return [str(item) for item in klines]

            try:
                return _retry(f"kline {scheme}://{host}", _once, retries=2)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{scheme}://{host}: {exc}")
    raise RuntimeError("kline failed on all hosts; " + "; ".join(errors[:3]))


def _bars_from_akshare(
    board_type: BoardType,
    code: str,
    start: date,
    end: date,
) -> list[BoardDailyBar]:
    period = _PERIOD_BY_TYPE[board_type]
    start_text = start.strftime("%Y%m%d")
    end_text = end.strftime("%Y%m%d")
    if board_type == "industry":
        frame = ak.stock_board_industry_hist_em(
            symbol=code,
            start_date=start_text,
            end_date=end_text,
            period=period,
            adjust="",
        )
    else:
        frame = ak.stock_board_concept_hist_em(
            symbol=code,
            period=period,
            start_date=start_text,
            end_date=end_text,
            adjust="",
        )
    if frame is None or frame.empty:
        raise RuntimeError("akshare hist empty")
    return [
        from_akshare_em_board_hist_row(
            row.to_dict(),
            board_type=board_type,
            board_code=code,
        )
        for _, row in frame.iterrows()
    ]


def _bars_from_push2his(
    board_type: BoardType,
    code: str,
    start: date,
    end: date,
) -> list[BoardDailyBar]:
    klines = _fetch_kline_raw(code, start, end)
    bars: list[BoardDailyBar] = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 11:
            continue
        raw = {
            "日期": parts[0],
            "开盘": parts[1],
            "收盘": parts[2],
            "最高": parts[3],
            "最低": parts[4],
            "成交量": parts[5],
            "成交额": parts[6],
            "振幅": parts[7],
            "涨跌幅": parts[8],
            "涨跌额": parts[9],
            "换手率": parts[10],
        }
        bars.append(
            from_akshare_em_board_hist_row(
                raw,
                board_type=board_type,
                board_code=code,
            )
        )
    if not bars:
        raise RuntimeError("push2his returned no parseable bars")
    return bars


class BoardDailyBarsFetchInfo:
    def __init__(
        self,
        bars: list[BoardDailyBar],
        source: str,
        attempts: list[str] | None = None,
    ):
        self.bars = bars
        self.source = source
        self.attempts = attempts or []


def fetch_board_daily_bars(
    board_type: BoardType,
    board_code: str,
    start: date,
    end: date,
) -> BoardDailyBarsFetchInfo:
    """Probe akshare hist then push2his; return bars + which source won."""
    global _last_good_kline_source
    code = board_code.strip().upper()
    ak_name = f"akshare_{board_type}_hist"
    methods: list[tuple[str, Callable[[], list[BoardDailyBar]]]] = [
        (ak_name, lambda: _bars_from_akshare(board_type, code, start, end)),
        ("push2his", lambda: _bars_from_push2his(board_type, code, start, end)),
    ]
    if _last_good_kline_source:
        methods.sort(key=lambda item: 0 if item[0] == _last_good_kline_source else 1)

    attempts: list[str] = []
    for name, fetch in methods:
        try:
            bars = fetch()
        except Exception as exc:  # noqa: BLE001 - source boundary
            attempts.append(f"{name}: fail ({exc})")
            continue
        if not bars:
            attempts.append(f"{name}: empty")
            continue
        _last_good_kline_source = name
        attempts.append(f"{name}: ok ({len(bars)} rows)")
        return BoardDailyBarsFetchInfo(bars, source=name, attempts=attempts)

    raise RuntimeError(
        f"all board daily-bar sources failed for {board_type}:{code}; "
        + " | ".join(attempts)
    )


_CONS_HOSTS = (
    "push2.eastmoney.com",
    "29.push2.eastmoney.com",
    "79.push2.eastmoney.com",
    "17.push2.eastmoney.com",
    "7.push2.eastmoney.com",
)

_last_good_cons_source: str | None = None


class BoardConstituentsFetchInfo:
    def __init__(
        self,
        rows: list[BoardConstituentRow],
        source: str,
        attempts: list[str] | None = None,
    ):
        self.rows = rows
        self.source = source
        self.attempts = attempts or []


def _cons_from_akshare(
    trade_date: date,
    board_type: BoardType,
    board_code: str,
) -> list[BoardConstituentRow]:
    if board_type == "industry":
        frame = ak.stock_board_industry_cons_em(symbol=board_code)
    else:
        frame = ak.stock_board_concept_cons_em(symbol=board_code)
    if frame is None or frame.empty:
        raise RuntimeError("akshare cons empty")
    rows: list[BoardConstituentRow] = []
    for _, raw in frame.iterrows():
        try:
            rows.append(
                from_akshare_em_board_cons_row(
                    raw.to_dict(),
                    trade_date=trade_date,
                    board_type=board_type,
                    board_code=board_code,
                )
            )
        except (KeyError, ValueError):
            continue
    if not rows:
        raise RuntimeError("akshare cons produced no valid rows")
    return rows


def _fetch_cons_clist_page(
    board_code: str,
    page: int,
    *,
    page_size: int = 100,
    timeout: float = 12.0,
) -> tuple[list[dict], int]:
    params = {
        "pn": str(page),
        "pz": str(page_size),
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f12",
        "fs": f"b:{board_code} f:!50",
        "fields": "f12,f14",
    }
    query = urlencode(params)
    errors: list[str] = []
    for host in _CONS_HOSTS:
        url = f"https://{host}/api/qt/clist/get?{query}"
        try:
            data = _http_get_json(url, timeout=timeout)
            payload = data.get("data") or {}
            diff = payload.get("diff") or []
            total = int(payload.get("total") or 0)
            return diff, total
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{host}: {exc}")
    raise RuntimeError("cons clist failed; " + "; ".join(errors[:3]))


def _cons_from_push2(
    trade_date: date,
    board_type: BoardType,
    board_code: str,
) -> list[BoardConstituentRow]:
    rows: list[BoardConstituentRow] = []
    page = 1
    while True:
        diff, total = _retry(
            f"cons {board_code} page {page}",
            lambda p=page: _fetch_cons_clist_page(board_code, p),
            retries=2,
        )
        if not diff:
            break
        for item in diff:
            try:
                rows.append(
                    from_akshare_em_board_cons_row(
                        item,
                        trade_date=trade_date,
                        board_type=board_type,
                        board_code=board_code,
                    )
                )
            except (KeyError, ValueError):
                continue
        if total and len(rows) >= total:
            break
        if len(diff) < 100:
            break
        page += 1
        if page > 100:
            break
        time.sleep(0.1)
    if not rows:
        raise RuntimeError("push2 cons produced no valid rows")
    # Deduplicate by stock_code while keeping first name.
    dedup: dict[str, BoardConstituentRow] = {}
    for row in rows:
        dedup.setdefault(row.stock_code, row)
    return list(dedup.values())


def fetch_board_constituents(
    trade_date: date,
    board_type: BoardType,
    board_code: str,
) -> BoardConstituentsFetchInfo:
    """Probe akshare cons then push2 clist; stock codes normalized to baostock."""
    global _last_good_cons_source
    code = board_code.strip().upper()
    ak_name = f"akshare_{board_type}_cons"
    methods: list[tuple[str, Callable[[], list[BoardConstituentRow]]]] = [
        (ak_name, lambda: _cons_from_akshare(trade_date, board_type, code)),
        ("push2_cons", lambda: _cons_from_push2(trade_date, board_type, code)),
    ]
    if _last_good_cons_source:
        methods.sort(key=lambda item: 0 if item[0] == _last_good_cons_source else 1)

    attempts: list[str] = []
    for name, fetch in methods:
        try:
            rows = fetch()
        except Exception as exc:  # noqa: BLE001
            attempts.append(f"{name}: fail ({exc})")
            continue
        if not rows:
            attempts.append(f"{name}: empty")
            continue
        _last_good_cons_source = name
        attempts.append(f"{name}: ok ({len(rows)} rows)")
        return BoardConstituentsFetchInfo(rows, source=name, attempts=attempts)

    raise RuntimeError(
        f"all board constituent sources failed for {board_type}:{code}; "
        + " | ".join(attempts)
    )
