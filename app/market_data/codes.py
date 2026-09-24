"""Stock code conversions between baostock and akshare providers."""

from __future__ import annotations


def to_baostock(code: str) -> str:
    value = code.strip().lower().replace("_", ".")
    if len(value) == 9 and value[2] == "." and value[:2] in {"sh", "sz", "bj"}:
        return value
    if value.startswith(("sh", "sz", "bj")) and len(value) == 8:
        return f"{value[:2]}.{value[2:]}"
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) != 6:
        raise ValueError(f"unsupported stock code: {code!r}")
    if digits.startswith(("5", "6", "9")):
        return f"sh.{digits}"
    if digits.startswith(("0", "1", "2", "3")):
        return f"sz.{digits}"
    if digits.startswith(("4", "8")):
        return f"bj.{digits}"
    raise ValueError(f"unsupported stock code: {code!r}")


def to_akshare_em(code: str) -> str:
    return to_baostock(code).split(".", 1)[1]


def to_akshare_tx(code: str) -> str:
    market, digits = to_baostock(code).split(".", 1)
    return f"{market}{digits}"
