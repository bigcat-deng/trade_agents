"""Normalize CLS and Tonghuashun flashes before they are appended."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from app.market_data.news_daily import SHANGHAI


@dataclass(frozen=True)
class FlashRow:
    source: str
    published_at: datetime
    title: str
    content: str
    url: str | None
    level: str | None

    def as_tuple(self) -> tuple:
        return (
            self.source,
            self.published_at,
            self.title,
            self.content,
            self.url,
            self.level,
        )


def normalize_cls(records: list[dict]) -> tuple[list[FlashRow], int]:
    return _normalize(records, source="cls", with_level=True)


def normalize_ths(records: list[dict]) -> tuple[list[FlashRow], int]:
    return _normalize(records, source="ths", with_level=False)


def _normalize(
    records: list[dict],
    *,
    source: str,
    with_level: bool,
) -> tuple[list[FlashRow], int]:
    skipped = 0
    by_key: dict[tuple[datetime, str], FlashRow] = {}
    for record in records:
        published_at = _published_at(record)
        title = " ".join(_text(record.get("标题")).split())
        if published_at is None or not title:
            skipped += 1
            continue
        level = None
        if with_level:
            raw_level = _text(record.get("等级"))
            level = raw_level[:8] if raw_level else None
        url = _text(record.get("链接")) or None
        if url and not url.startswith(("http://", "https://")):
            url = None
        by_key[(published_at, title)] = FlashRow(
            source=source,
            published_at=published_at,
            title=title,
            content=_text(record.get("内容")),
            url=url,
            level=level,
        )
    return list(by_key.values()), skipped


def _published_at(record: dict) -> datetime | None:
    clock = record.get("发布时间")
    day = record.get("发布日期")
    if day is not None and clock is not None:
        combined = _combine(day, clock)
        if combined is not None:
            return combined
    if isinstance(clock, datetime):
        if clock.tzinfo is None:
            return clock.replace(tzinfo=SHANGHAI)
        return clock.astimezone(SHANGHAI)
    text = _text(clock)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=SHANGHAI)
        except ValueError:
            continue
    return None


def _combine(day: object, clock: object) -> datetime | None:
    parsed_day = _as_date(day)
    parsed_clock = _as_time(clock)
    if parsed_day is None or parsed_clock is None:
        return None
    return datetime.combine(parsed_day, parsed_clock, tzinfo=SHANGHAI)


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    for fmt, size in (("%Y-%m-%d", 10), ("%Y%m%d", 8)):
        try:
            return datetime.strptime(text[:size], fmt).date()
        except ValueError:
            continue
    return None


def _as_time(value: object) -> time | None:
    if isinstance(value, datetime):
        return value.time().replace(tzinfo=None)
    if isinstance(value, time):
        return value.replace(tzinfo=None)
    text = _text(value)
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    if type(value).__name__ in {"NAType", "NaTType"}:
        return ""
    return str(value).strip()
