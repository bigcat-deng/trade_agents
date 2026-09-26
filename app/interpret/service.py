"""Page-independent interpretation. Callers pass a prompt template name."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from app.db import fetch_interpret_result, save_interpret_result
from app.interpret.cross_stats import attach_cross_stats
from app.interpret.industry_heat import (
    build_heat_prompt,
    interpret_industry_heat,
    model_settings,
    normalize_reading,
)
from app.prompts.template import load_prompt


def _heat_builder(template_name: str):
    def build(as_of: date | None = None):
        return build_heat_prompt(template_name, as_of)

    return build


BUILDERS = {
    "industry-heat-rotation": _heat_builder("industry-heat-rotation"),
    "concept-heat-rotation": _heat_builder("concept-heat-rotation"),
}


class InterpretError(Exception):
    """Base error for the interpretation service."""


class UnknownTemplate(InterpretError):
    def __init__(self, name: str) -> None:
        super().__init__(f"unknown interpret template: {name}")
        self.name = name


class InterpretConfigError(InterpretError):
    def __init__(self, missing: list[str]) -> None:
        super().__init__("model settings missing: " + ", ".join(missing))
        self.missing = missing


class InterpretFormatError(InterpretError):
    """The model reply could not be turned into the expected tables."""


@dataclass(frozen=True)
class Interpretation:
    template: str
    as_of: date
    model: str
    content: str
    reading: dict
    cached: bool


def interpret(template_name: str, as_of: date | None = None) -> Interpretation:
    """Fill one prompt template and return the model reading, using a saved result when present."""
    builder = BUILDERS.get(template_name)
    if builder is None:
        try:
            load_prompt(template_name)
        except FileNotFoundError as exc:
            raise UnknownTemplate(template_name) from exc
        raise UnknownTemplate(template_name)

    template, prompt, resolved, latest, summaries = builder(as_of)
    board_type = str(template.config.get("board_type") or "industry")
    settings = model_settings(template)
    missing = [
        name
        for name, value in (
            ("LLM_BASE_URL", settings["base_url"]),
            ("LLM_MODEL", settings["model"]),
            ("LLM_API_KEY", settings["api_key"]),
        )
        if not value
    ]
    if missing:
        raise InterpretConfigError(missing)

    request_model = settings["model"]
    stored = fetch_interpret_result(template.name, resolved, request_model)
    if stored is not None:
        response_model, content = stored
        reading = normalize_reading(content, latest, summaries)
        if reading is not None:
            return Interpretation(
                template=template.name,
                as_of=resolved,
                model=response_model,
                content=json.dumps(reading, ensure_ascii=False),
                reading=attach_cross_stats(reading, resolved, board_type),
                cached=True,
            )

    content, response_model = interpret_industry_heat(prompt, settings)
    reading = normalize_reading(content, latest, summaries)
    if reading is None:
        content, response_model = interpret_industry_heat(
            prompt + "\n\n只输出一个 JSON 对象，键名使用 conclusion、aligned、divergent、price_split、watch。",
            settings,
        )
        reading = normalize_reading(content, latest, summaries)
    if reading is None:
        raise InterpretFormatError("model reply is not the expected JSON reading")

    saved = json.dumps(reading, ensure_ascii=False)
    save_interpret_result(
        template.name,
        resolved,
        request_model,
        response_model,
        saved,
    )
    return Interpretation(
        template=template.name,
        as_of=resolved,
        model=response_model,
        content=saved,
        reading=attach_cross_stats(reading, resolved, board_type),
        cached=False,
    )
