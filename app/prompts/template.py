"""Load prompt templates stored under prompts/<name>/prompt.md."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    description: str
    body: str
    config: dict


def load_prompt(name: str) -> PromptTemplate:
    path = PROMPTS_DIR / name / "prompt.md"
    text = path.read_text(encoding="utf-8")
    config, body = _split_frontmatter(text)
    return PromptTemplate(
        name=str(config.get("name") or name),
        description=str(config.get("description") or ""),
        body=body,
        config=config,
    )


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    raw = text[3:end].strip("\n")
    body = text[end + 4 :].lstrip("\n")
    return _parse_block(raw), body


def _parse_block(raw: str) -> dict:
    lines = [line for line in raw.splitlines() if line.strip() and not line.strip().startswith("#")]
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    for index, line in enumerate(lines):
        indent = len(line) - len(line.lstrip(" "))
        key, _, value = line.strip().partition(":")
        value = value.strip()
        while stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if value == "" and _next_indent(lines, index) > indent:
            child: dict = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _coerce(value)
    return root


def _next_indent(lines: list[str], index: int) -> int:
    if index + 1 >= len(lines):
        return -1
    line = lines[index + 1]
    return len(line) - len(line.lstrip(" "))


def _coerce(value: str) -> str | int:
    if value.isdigit():
        return int(value)
    return value
