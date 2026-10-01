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
from app.interpret.medicine_theme import (
    PROSE_THEME_TEMPLATES,
    build_ai_theme_prompt,
    build_battery_theme_prompt,
    build_defense_theme_prompt,
    build_energy_theme_prompt,
    build_finance_theme_prompt,
    build_food_theme_prompt,
    build_medicine_theme_prompt,
    build_metals_theme_prompt,
    build_property_theme_prompt,
    build_renewables_theme_prompt,
    build_robots_theme_prompt,
    build_semiconductor_theme_prompt,
    interpret_prose,
    prose_reading,
)
from app.interpret.theme_wave import build_theme_wave_reading_prompt
from app.interpret.concept_wavelet import build_concept_wavelet_reading_prompt
from app.interpret.industry_wavelet import build_industry_wavelet_reading_prompt
from app.prompts.template import load_prompt


def _heat_builder(template_name: str):
    def build(as_of: date | None = None):
        return build_heat_prompt(template_name, as_of)

    return build


BUILDERS = {
    "industry-heat-rotation": _heat_builder("industry-heat-rotation"),
    "concept-heat-rotation": _heat_builder("concept-heat-rotation"),
    "medicine-theme-reading": build_medicine_theme_prompt,
    "ai-theme-reading": build_ai_theme_prompt,
    "semiconductor-theme-reading": build_semiconductor_theme_prompt,
    "metals-theme-reading": build_metals_theme_prompt,
    "energy-theme-reading": build_energy_theme_prompt,
    "defense-theme-reading": build_defense_theme_prompt,
    "renewables-theme-reading": build_renewables_theme_prompt,
    "battery-theme-reading": build_battery_theme_prompt,
    "robots-theme-reading": build_robots_theme_prompt,
    "food-theme-reading": build_food_theme_prompt,
    "finance-theme-reading": build_finance_theme_prompt,
    "property-theme-reading": build_property_theme_prompt,
    "theme-wave-reading": build_theme_wave_reading_prompt,
    "concept-wavelet-reading": build_concept_wavelet_reading_prompt,
    "industry-wavelet-reading": build_industry_wavelet_reading_prompt,
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


WAVELET_READING_TEMPLATES = frozenset(
    {
        "concept-wavelet-reading",
        "industry-wavelet-reading",
    }
)


def interpret(
    template_name: str,
    as_of: date | None = None,
    *,
    force: bool = False,
    window_trading_days: int | None = None,
) -> Interpretation:
    """Fill one prompt template and return the model reading, using a saved result when present."""
    builder = BUILDERS.get(template_name)
    if builder is None:
        try:
            load_prompt(template_name)
        except FileNotFoundError as exc:
            raise UnknownTemplate(template_name) from exc
        raise UnknownTemplate(template_name)

    if template_name in PROSE_THEME_TEMPLATES:
        return _interpret_prose(
            template_name,
            builder,
            as_of,
            force=force,
            window_trading_days=window_trading_days,
        )

    if window_trading_days is not None:
        raise InterpretError(
            f"window_trading_days is only supported for wavelet reading templates, not {template_name}"
        )

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
    if not force:
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


def _interpret_prose(
    template_name: str,
    builder,
    as_of: date | None,
    *,
    force: bool = False,
    window_trading_days: int | None = None,
) -> Interpretation:
    if template_name in WAVELET_READING_TEMPLATES:
        template, prompt, resolved = builder(
            as_of, window_trading_days=window_trading_days
        )
        # Include window in cache key so ?days=40 and ?days=60 do not collide.
        resolved_window = window_trading_days
        if resolved_window is None:
            resolved_window = int(template.config.get("window_trading_days") or 60)
        resolved_window = max(20, min(180, int(resolved_window)))
        cache_name = f"{template.name}#d{resolved_window}"
    else:
        if window_trading_days is not None:
            raise InterpretError(
                f"window_trading_days is not supported for template {template_name}"
            )
        template, prompt, resolved = builder(as_of)
        cache_name = template.name

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
    if not force:
        stored = fetch_interpret_result(cache_name, resolved, request_model)
        if stored is not None:
            response_model, content = stored
            reading = prose_reading(content)
            if reading.get("conclusion"):
                return Interpretation(
                    template=template.name,
                    as_of=resolved,
                    model=response_model,
                    content=json.dumps(reading, ensure_ascii=False),
                    reading=reading,
                    cached=True,
                )

    text, response_model = interpret_prose(prompt, settings)
    reading = prose_reading(text)
    if not reading.get("conclusion"):
        raise InterpretFormatError("model reply is empty")
    saved = json.dumps(reading, ensure_ascii=False)
    save_interpret_result(
        cache_name,
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
        reading=reading,
        cached=False,
    )
