"""Normalize the close-of-day news snapshot before it is stored."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from app.market_data.codes import to_baostock

SHANGHAI = ZoneInfo("Asia/Shanghai")
CLOSE_CUTOFF = time(15, 5)
CCTV_READY_AT = time(19, 30)
MIN_COMMENT_ROWS = 5000
WEIBO_PERIOD = "CNHOUR24"
NOTICE_TYPES = ("重大事项", "风险提示", "资产重组", "持股变动")

SNAPSHOT_FEEDS = (
    "stock_comment",
    "em_rank",
    "em_surge",
    "weibo",
    "stock_notice",
    "cctv",
)


@dataclass(frozen=True)
class CommentRow:
    trade_date: date
    code: str
    name: str
    close: float | None
    pct_chg: float | None
    turnover: float | None
    pe: float | None
    main_cost: float | None
    inst_participation: float | None
    score: float | None
    rank_change: int | None
    rank_no: int | None
    focus: float | None

    def as_tuple(self) -> tuple:
        return (
            self.trade_date,
            self.code,
            self.name,
            self.close,
            self.pct_chg,
            self.turnover,
            self.pe,
            self.main_cost,
            self.inst_participation,
            self.score,
            self.rank_change,
            self.rank_no,
            self.focus,
            "eastmoney",
        )


@dataclass(frozen=True)
class HotRankRow:
    trade_date: date
    list_name: str
    code: str
    name: str
    rank_no: int | None
    rank_change: int | None
    close: float | None
    change_amt: float | None
    pct_chg: float | None

    def as_tuple(self) -> tuple:
        return (
            self.trade_date,
            self.list_name,
            self.code,
            self.name,
            self.rank_no,
            self.rank_change,
            self.close,
            self.change_amt,
            self.pct_chg,
            "eastmoney",
        )


@dataclass(frozen=True)
class WeiboRow:
    trade_date: date
    time_period: str
    name: str
    code: str | None
    rate: float | None

    def as_tuple(self) -> tuple:
        return (
            self.trade_date,
            self.time_period,
            self.name,
            self.code,
            self.rate,
            "jin10",
        )


@dataclass(frozen=True)
class NoticeRow:
    notice_id: str
    notice_date: date
    code: str
    name: str
    notice_type: str
    title: str
    url: str | None

    def as_tuple(self) -> tuple:
        return (
            self.notice_id,
            self.notice_date,
            self.code,
            self.name,
            self.notice_type,
            self.title,
            self.url,
            "eastmoney",
        )


@dataclass(frozen=True)
class CctvRow:
    broadcast_date: date
    title: str
    content: str

    def as_tuple(self) -> tuple:
        return (self.broadcast_date, self.title, self.content, "cctv")


@dataclass
class FeedOutcome:
    feed: str
    status: str
    snapshot_date: date | None
    reported_rows: int
    error: str | None
    replace: bool
    rows: list = field(default_factory=list)
    notice_types: tuple[str, ...] = ()
    note: str = ""


class NewsSources(Protocol):
    def comment(self) -> list[dict]: ...

    def hot_rank(self) -> list[dict]: ...

    def hot_surge(self) -> list[dict]: ...

    def weibo(self) -> list[dict]: ...

    def notices(self, notice_type: str, day: date) -> list[dict]: ...

    def cctv(self, day: date) -> list[dict]: ...

    def universe_names(self) -> list[tuple[str, str]]: ...


def shanghai_now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(SHANGHAI)
    if now.tzinfo is None:
        return now.replace(tzinfo=SHANGHAI)
    return now.astimezone(SHANGHAI)


def session_date(now: datetime | None = None) -> date:
    """Session the close snapshot belongs to.

    At or after 15:05 on a weekday, that calendar day. Earlier the same day,
    and any weekend, the previous weekday.
    """
    current = shanghai_now(now)
    day = current.date()
    if current.weekday() < 5 and current.time() >= CLOSE_CUTOFF:
        return day
    day = day - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def cctv_ready(now: datetime | None, broadcast_date: date) -> bool:
    current = shanghai_now(now)
    ready_at = datetime.combine(broadcast_date, CCTV_READY_AT, tzinfo=SHANGHAI)
    return current >= ready_at


def normalize_stock_name(name: str) -> str:
    return (
        name.replace(" ", "")
        .replace("\u3000", "")
        .replace("Ａ", "A")
        .replace("ａ", "a")
        .strip()
        .lower()
    )


def name_index(pairs: list[tuple[str, str]]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for code, raw_name in pairs:
        key = normalize_stock_name(raw_name)
        if not key:
            continue
        bucket = index.setdefault(key, [])
        if code not in bucket:
            bucket.append(code)
    return index


def resolve_name(name: str, index: dict[str, list[str]]) -> str | None:
    codes = index.get(normalize_stock_name(name), [])
    if len(codes) == 1:
        return codes[0]
    return None


def collect_snapshot(
    sources: NewsSources,
    now: datetime | None = None,
    *,
    minimum_comment_rows: int = MIN_COMMENT_ROWS,
) -> list[FeedOutcome]:
    current = shanghai_now(now)
    session = session_date(current)
    try:
        universe = sources.universe_names()
        universe_error = None
    except Exception as exc:  # noqa: BLE001 - one feed must not block the rest
        universe = []
        universe_error = _short_error(exc)

    outcomes = [
        _comment_outcome(sources, minimum=minimum_comment_rows),
        _hot_outcome(sources.hot_rank, session, "rank", "em_rank"),
        _hot_outcome(sources.hot_surge, session, "surge", "em_surge"),
        _weibo_outcome(sources, session, name_index(universe), universe_error),
        _notice_outcome(sources, session),
        _cctv_outcome(sources, current, session),
    ]
    return outcomes


def _comment_outcome(sources: NewsSources, *, minimum: int) -> FeedOutcome:
    records, error = _call(sources.comment)
    if error:
        return _failed("stock_comment", error)
    trade_date, rows, skipped = normalize_comment(records or [])
    note = f"skipped={skipped}" if skipped else ""
    if trade_date is None or len(rows) < minimum:
        count = len(rows)
        return FeedOutcome(
            feed="stock_comment",
            status="error",
            snapshot_date=None,
            reported_rows=count,
            error=f"rows={count} < {minimum}",
            replace=False,
            note=note,
        )
    return FeedOutcome(
        feed="stock_comment",
        status="ok",
        snapshot_date=trade_date,
        reported_rows=len(rows),
        error=None,
        replace=True,
        rows=rows,
        note=note,
    )


def _hot_outcome(fetch, session: date, list_name: str, feed: str) -> FeedOutcome:
    records, error = _call(fetch)
    if error:
        return _failed(feed, error)
    rows, skipped = normalize_hot_rank(
        records or [], trade_date=session, list_name=list_name
    )
    note = f"skipped={skipped}" if skipped else ""
    if not rows:
        return FeedOutcome(
            feed=feed,
            status="error",
            snapshot_date=None,
            reported_rows=0,
            error="empty",
            replace=False,
            note=note,
        )
    return FeedOutcome(
        feed=feed,
        status="ok",
        snapshot_date=session,
        reported_rows=len(rows),
        error=None,
        replace=True,
        rows=rows,
        note=note,
    )


def _weibo_outcome(
    sources: NewsSources,
    session: date,
    index: dict[str, list[str]],
    universe_error: str | None,
) -> FeedOutcome:
    records, error = _call(sources.weibo)
    if error:
        return _failed("weibo", error)
    rows, skipped = normalize_weibo(
        records or [], trade_date=session, index=index
    )
    notes = []
    if skipped:
        notes.append(f"skipped={skipped}")
    if universe_error:
        notes.append(f"universe: {universe_error}")
    if not rows:
        return FeedOutcome(
            feed="weibo",
            status="error",
            snapshot_date=None,
            reported_rows=0,
            error="empty",
            replace=False,
            note="; ".join(notes),
        )
    return FeedOutcome(
        feed="weibo",
        status="ok",
        snapshot_date=session,
        reported_rows=len(rows),
        error=None,
        replace=True,
        rows=rows,
        note="; ".join(notes),
    )


def _notice_outcome(sources: NewsSources, session: date) -> FeedOutcome:
    rows: list[NoticeRow] = []
    ok_types: list[str] = []
    errors: list[str] = []
    skipped = 0
    for notice_type in NOTICE_TYPES:
        records, error = _call(lambda notice_type=notice_type: sources.notices(notice_type, session))
        if error:
            errors.append(f"{notice_type}: {error}")
            continue
        parsed, type_skipped = normalize_notices(
            records or [], notice_type=notice_type, notice_date=session
        )
        skipped += type_skipped
        ok_types.append(notice_type)
        rows.extend(parsed)
    note = f"skipped={skipped}" if skipped else ""
    if not ok_types:
        return FeedOutcome(
            feed="stock_notice",
            status="error",
            snapshot_date=None,
            reported_rows=0,
            error="; ".join(errors) or "empty",
            replace=False,
            note=note,
        )
    return FeedOutcome(
        feed="stock_notice",
        status="error" if errors else "ok",
        snapshot_date=session,
        reported_rows=len(rows),
        error="; ".join(errors) or None,
        replace=True,
        rows=rows,
        notice_types=tuple(ok_types),
        note=note,
    )


def _cctv_outcome(sources: NewsSources, now: datetime, session: date) -> FeedOutcome:
    if not cctv_ready(now, session):
        return FeedOutcome(
            feed="cctv",
            status="pending",
            snapshot_date=None,
            reported_rows=0,
            error="联播未到播出时间",
            replace=False,
        )
    records, error = _call(lambda: sources.cctv(session))
    if error:
        return FeedOutcome(
            feed="cctv",
            status="error",
            snapshot_date=None,
            reported_rows=0,
            error=error,
            replace=False,
        )
    rows, skipped = normalize_cctv(records or [], broadcast_date=session)
    note = f"skipped={skipped}" if skipped else ""
    if not rows:
        return FeedOutcome(
            feed="cctv",
            status="pending",
            snapshot_date=None,
            reported_rows=0,
            error="联播正文为空",
            replace=False,
            note=note,
        )
    return FeedOutcome(
        feed="cctv",
        status="ok",
        snapshot_date=session,
        reported_rows=len(rows),
        error=None,
        replace=True,
        rows=rows,
        note=note,
    )


def normalize_comment(
    records: list[dict],
) -> tuple[date | None, list[CommentRow], int]:
    skipped = 0
    by_date: dict[date, dict[str, CommentRow]] = {}
    for record in records:
        trade_date = _as_date(record.get("交易日"))
        name = _text(record.get("名称"))[:64]
        if trade_date is None or not name:
            skipped += 1
            continue
        try:
            code = to_baostock(_text(record.get("代码")))
        except ValueError:
            skipped += 1
            continue
        by_date.setdefault(trade_date, {})[code] = CommentRow(
            trade_date=trade_date,
            code=code,
            name=name,
            close=_num(record.get("最新价")),
            pct_chg=_num(record.get("涨跌幅")),
            turnover=_num(record.get("换手率")),
            pe=_num(record.get("市盈率")),
            main_cost=_num(record.get("主力成本")),
            inst_participation=_num(record.get("机构参与度")),
            score=_num(record.get("综合得分")),
            rank_change=_int(record.get("上升")),
            rank_no=_int(record.get("目前排名")),
            focus=_num(record.get("关注指数")),
        )
    if not by_date:
        return None, [], skipped
    chosen = max(by_date, key=lambda day: len(by_date[day]))
    skipped += sum(len(rows) for day, rows in by_date.items() if day != chosen)
    return chosen, list(by_date[chosen].values()), skipped


def hot_list_records(
    items: list[dict],
    *,
    names: dict[str, str],
    quotes: dict[str, dict] | None = None,
    bars: dict[str, dict] | None = None,
    surge: bool = False,
) -> list[dict]:
    """Build hot-list rows from the rank payload.

    Eastmoney's rank API has codes and ranks only. Quotes are optional;
    names and the session close come from local data when the quote host
    does not answer.
    """
    quote_map = quotes or {}
    bar_map = bars or {}
    records: list[dict] = []
    for item in items:
        raw = _text(item.get("sc")).upper()
        if not raw:
            continue
        try:
            code = to_baostock(raw)
        except ValueError:
            continue
        quote = quote_map.get(raw) or {}
        bar = bar_map.get(code) or {}
        name = _text(quote.get("name")) or _text(names.get(code))
        close = quote.get("close")
        pct = quote.get("pct")
        change = quote.get("change")
        if _missing(close):
            close = bar.get("close")
        if _missing(pct):
            pct = bar.get("pct_chg")
        if _missing(change):
            preclose = bar.get("preclose")
            if not _missing(close) and not _missing(preclose):
                try:
                    change = float(close) - float(preclose)
                except (TypeError, ValueError):
                    change = None
        record = {
            "代码": raw,
            "股票名称": name,
            "当前排名": item.get("rk"),
            "最新价": close,
            "涨跌额": change,
            "涨跌幅": pct,
        }
        if surge:
            record["排名较昨日变动"] = item.get("hrc")
        records.append(record)
    return records


def normalize_hot_rank(
    records: list[dict],
    *,
    trade_date: date,
    list_name: str,
) -> tuple[list[HotRankRow], int]:
    skipped = 0
    by_code: dict[str, HotRankRow] = {}
    for record in records:
        name = _text(record.get("股票名称"))[:64]
        if not name:
            skipped += 1
            continue
        try:
            code = to_baostock(_text(record.get("代码")))
        except ValueError:
            skipped += 1
            continue
        by_code[code] = HotRankRow(
            trade_date=trade_date,
            list_name=list_name,
            code=code,
            name=name,
            rank_no=_int(record.get("当前排名")),
            rank_change=_int(record.get("排名较昨日变动")),
            close=_num(record.get("最新价")),
            change_amt=_num(record.get("涨跌额")),
            pct_chg=_num(record.get("涨跌幅")),
        )
    return list(by_code.values()), skipped


def normalize_weibo(
    records: list[dict],
    *,
    trade_date: date,
    index: dict[str, list[str]],
) -> tuple[list[WeiboRow], int]:
    skipped = 0
    by_name: dict[str, WeiboRow] = {}
    for record in records:
        name = _text(record.get("name"))[:64]
        if not name:
            skipped += 1
            continue
        by_name[name] = WeiboRow(
            trade_date=trade_date,
            time_period=WEIBO_PERIOD,
            name=name,
            code=resolve_name(name, index),
            rate=_num(record.get("rate")),
        )
    return list(by_name.values()), skipped


def normalize_notices(
    records: list[dict],
    *,
    notice_type: str,
    notice_date: date,
) -> tuple[list[NoticeRow], int]:
    skipped = 0
    by_id: dict[str, NoticeRow] = {}
    for record in records:
        notice_id = _notice_id(record)
        title = _text(record.get("公告标题"))
        name = _text(record.get("名称"))[:64]
        row_date = _as_date(record.get("公告日期")) or notice_date
        if not notice_id or not title or not name or row_date != notice_date:
            skipped += 1
            continue
        try:
            code = to_baostock(_text(record.get("代码")))
        except ValueError:
            skipped += 1
            continue
        url = _text(record.get("网址")) or None
        by_id[notice_id] = NoticeRow(
            notice_id=notice_id,
            notice_date=notice_date,
            code=code,
            name=name,
            notice_type=notice_type,
            title=title,
            url=url,
        )
    return list(by_id.values()), skipped


def normalize_cctv(
    records: list[dict],
    *,
    broadcast_date: date,
) -> tuple[list[CctvRow], int]:
    skipped = 0
    by_title: dict[str, CctvRow] = {}
    for record in records:
        title = _text(record.get("title") or record.get("标题"))
        if not title:
            skipped += 1
            continue
        if title in by_title:
            skipped += 1
            continue
        content = _text(record.get("content") or record.get("内容"))
        by_title[title] = CctvRow(
            broadcast_date=broadcast_date,
            title=title,
            content=content,
        )
    return list(by_title.values()), skipped


def _notice_id(record: dict) -> str:
    explicit = _text(record.get("编码"))
    if explicit:
        return explicit[:64]
    url = _text(record.get("网址"))
    match = re.search(r"/([A-Za-z0-9]+)\.html(?:$|\?)", url)
    if not match:
        return ""
    return match.group(1)[:64]


def _failed(feed: str, error: str) -> FeedOutcome:
    return FeedOutcome(
        feed=feed,
        status="error",
        snapshot_date=None,
        reported_rows=0,
        error=error,
        replace=False,
    )


def _call(fetch) -> tuple[list[dict] | None, str | None]:
    try:
        return list(fetch()), None
    except Exception as exc:  # noqa: BLE001 - record the feed and continue
        return None, _short_error(exc)


def _short_error(exc: BaseException) -> str:
    text = " ".join(str(exc).split()) or exc.__class__.__name__
    for marker in (" with url:", " for url:"):
        if marker in text:
            text = text.split(marker, 1)[0]
            break
    return text[:180]


def _missing(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return value is None
    if isinstance(value, float) and value != value:
        return True
    return type(value).__name__ in {"NAType", "NaTType"}


def _text(value: object) -> str:
    if _missing(value):
        return ""
    return str(value).strip()


def _num(value: object) -> float | None:
    if _missing(value) or isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _int(value: object) -> int | None:
    number = _num(value)
    if number is None:
        return None
    return int(number)


def _as_date(value: object) -> date | None:
    if _missing(value) or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text == "NaT":
        return None
    for fmt, size in (("%Y-%m-%d", 10), ("%Y%m%d", 8)):
        try:
            return datetime.strptime(text[:size], fmt).date()
        except ValueError:
            continue
    return None
