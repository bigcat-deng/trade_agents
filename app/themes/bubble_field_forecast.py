"""Look-at-chart → bubble structure field → redraw industry heat forecast."""

from __future__ import annotations

import base64
import json
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from jinja2 import StrictUndefined, Template

from app.interpret.industry_heat import model_settings
from app.prompts.template import PromptTemplate, load_prompt
from app.themes.heat_forecast import FORECAST_CONTEXT_DAYS
from app.themes.heat_seriation import (
    densify_hotness_plane,
    hotness_grid,
)

TEMPLATE_NAME = "industry-heat-bubble-forecast"
REF_CONTEXT_DAYS = 40
TIP_PERSIST_DECAY = 0.72
BLOB_FLOOR = 0.05


def render_industry_heat_reference_png(
    *,
    tip: date,
    hist: list[date],
    heat_by_day: dict[date, dict[str, float]],
    names: dict[str, str],
    ordered: list[str],
    out_path: Path,
) -> Path:
    """Export tip-locked historical plane as PNG for vision input."""
    import matplotlib

    # FastAPI worker threads cannot use macOS GUI backends.
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.colors import LinearSegmentedColormap

    from app.charts.theme_wave import _COLORSCALE

    labels = [names.get(c, c) for c in ordered]
    z = hotness_grid(
        window_dates=hist, ordered_codes=ordered, heat_by_day=heat_by_day
    )
    x = [float(i) for i in range(len(ordered))]
    _, dense_z = densify_hotness_plane(theme_x=x, z_short=z, densify=3)
    cmap = LinearSegmentedColormap.from_list(
        "theme_heat", [(s, c) for s, c in _COLORSCALE]
    )
    for fname in ("PingFang SC", "Heiti SC", "Arial Unicode MS", "Noto Sans CJK SC"):
        if any(fname in f.name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.sans-serif"] = [fname]
            break
    plt.rcParams["axes.unicode_minus"] = False

    arr = np.array(
        [[(np.nan if v is None else v) for v in row] for row in dense_z], dtype=float
    )
    fig, ax = plt.subplots(figsize=(14, 6.8), dpi=140)
    fig.patch.set_facecolor("#fffdf8")
    ax.set_facecolor("#fffdf8")
    im = ax.imshow(
        arr,
        aspect="auto",
        origin="lower",
        cmap=cmap,
        vmin=0,
        vmax=1,
        interpolation="bilinear",
        extent=(-0.5, len(ordered) - 0.5, -0.5, len(hist) - 0.5),
    )
    ax.axhline(len(hist) - 0.5, color="#1c1917", lw=1.2, ls="--", alpha=0.8)
    ax.text(
        0.2,
        len(hist) - 0.35,
        "截止日 ↑ 请从这里往上续气泡",
        color="#1c1917",
        fontsize=9,
        va="bottom",
    )
    yticks = list(range(0, len(hist), 5)) + [len(hist) - 1]
    ax.set_yticks(yticks)
    ax.set_yticklabels([hist[i].isoformat()[5:] for i in yticks], fontsize=8)
    step = max(1, len(ordered) // 16)
    xticks = list(range(0, len(ordered), step))
    ax.set_xticks(xticks)
    ax.set_xticklabels([labels[i] for i in xticks], rotation=55, ha="right", fontsize=7)
    ax.set_title(f"行业短热 · 实盘底图（截止 {tip.isoformat()}）", fontsize=12)
    ax.set_xlabel("行业（轨迹叶序）")
    ax.set_ylabel("交易日")
    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cbar.set_label("热度")
    cbar.set_ticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return out_path


def build_bubble_forecast_prompt(
    *,
    tip: date,
    forecast_dates: list[date],
) -> tuple[PromptTemplate, str]:
    template = load_prompt(TEMPLATE_NAME)
    n = int(template.config.get("forecast_trading_days") or len(forecast_dates))
    body = Template(template.body, undefined=StrictUndefined).render(
        as_of=tip.isoformat(),
        forecast_trading_days=n,
        forecast_dates=", ".join(d.isoformat() for d in forecast_dates),
    )
    return template, body


def call_bubble_vision_llm(
    *,
    prompt: str,
    image_path: Path,
    template: PromptTemplate,
) -> tuple[dict[str, Any], str]:
    """Send reference PNG + prompt; return structure-field JSON and model id."""
    settings = model_settings(template)
    missing = [k for k in ("base_url", "model", "api_key") if not settings.get(k)]
    if missing:
        raise RuntimeError(f"LLM settings missing: {', '.join(missing)}")
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    payload = json.dumps(
        {
            "model": settings["model"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{b64}"
                            },
                        },
                    ],
                }
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.5,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{settings['base_url'].rstrip('/')}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {settings['api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        body = json.loads(response.read().decode("utf-8"))
    content = body["choices"][0]["message"]["content"]
    model_id = str(body.get("model") or settings["model"])
    scenario = json.loads(content)
    if not isinstance(scenario, dict):
        raise RuntimeError("bubble-field reply is not a JSON object")
    return scenario, model_id


def rasterize_bubble_field(
    *,
    n_boards: int,
    n_days: int,
    scenario: dict[str, Any],
    tip_row: list[float | None] | None = None,
) -> list[list[float]]:
    """Rasterize LLM blobs onto forecast days × boards hotness grid in [0,1]."""
    if n_boards < 1 or n_days < 1:
        return []
    field = np.zeros((n_days, n_boards), dtype=float)
    days = list(scenario.get("days") or [])
    # Collect all blobs (may be repeated across days); also accept day-local blobs.
    all_blobs: list[dict[str, Any]] = []
    for spec in days:
        if not isinstance(spec, dict):
            continue
        for blob in spec.get("blobs") or []:
            if isinstance(blob, dict):
                all_blobs.append(blob)
    if not all_blobs:
        # Fallback: persist tip.
        if tip_row:
            for i in range(n_days):
                decay = TIP_PERSIST_DECAY ** (i + 1)
                for j, v in enumerate(tip_row):
                    if v is None or not np.isfinite(v):
                        continue
                    field[i, j] = max(field[i, j], float(v) * decay)
        return field.tolist()

    xs = np.linspace(0.0, 1.0, n_boards)
    ts = np.linspace(0.0, 1.0, n_days) if n_days > 1 else np.array([0.0])
    for blob in all_blobs:
        try:
            cx = float(blob.get("cx"))
            ct = float(blob.get("ct", 0.5))
            rx = max(0.02, float(blob.get("rx", 0.06)))
            rt = max(0.08, float(blob.get("rt", 0.25)))
            peak = float(blob.get("peak", 0.8))
        except (TypeError, ValueError):
            continue
        peak = float(np.clip(peak, 0.0, 1.0))
        cx = float(np.clip(cx, 0.0, 1.0))
        ct = float(np.clip(ct, 0.0, 1.0))
        gx = np.exp(-0.5 * ((xs - cx) / rx) ** 2)
        gt = np.exp(-0.5 * ((ts - ct) / rt) ** 2)
        field = np.maximum(field, peak * np.outer(gt, gx))

    if tip_row:
        tip_arr = np.array(
            [0.0 if v is None or not np.isfinite(v) else float(v) for v in tip_row],
            dtype=float,
        )
        for i in range(n_days):
            decay = TIP_PERSIST_DECAY ** (i + 1)
            field[i] = np.maximum(field[i], tip_arr * decay * 0.55)

    field = np.clip(field, 0.0, 1.0)
    field[field < BLOB_FLOOR] = np.maximum(field[field < BLOB_FLOOR], 0.0)
    return field.tolist()


def build_bubble_forecast_plane(
    *,
    tip: date,
    hist: list[date],
    heat_by_day: dict[date, dict[str, float]],
    names: dict[str, str],
    ordered: list[str],
    forecast_dates: list[date],
    scenario: dict[str, Any],
) -> dict[str, Any]:
    """Context actual hotness + rasterized bubble forecast, densified for plot."""
    context = hist[-FORECAST_CONTEXT_DAYS:]
    z_hist = hotness_grid(
        window_dates=context, ordered_codes=ordered, heat_by_day=heat_by_day
    )
    tip_row = z_hist[-1] if z_hist else [None] * len(ordered)
    forecast_z = rasterize_bubble_field(
        n_boards=len(ordered),
        n_days=len(forecast_dates),
        scenario=scenario,
        tip_row=tip_row,
    )
    display_dates = list(context) + list(forecast_dates)
    z_native = list(z_hist) + [
        [float(v) for v in row] for row in forecast_z
    ]
    x_ticks = list(range(len(ordered)))
    dense_x, dense_z = densify_hotness_plane(
        theme_x=[float(i) for i in x_ticks],
        z_short=z_native,
        densify=4,
    )
    labels = [names.get(c, c) for c in ordered]
    thesis = str(scenario.get("thesis") or "").strip()
    read_image = str(scenario.get("read_image") or "").strip()
    notes = []
    for spec in scenario.get("days") or []:
        if isinstance(spec, dict) and spec.get("note"):
            d = str(spec.get("date") or "")
            notes.append(f"{d[5:] if len(d) >= 10 else d} {spec['note']}")
    scenario_note = thesis
    if read_image:
        scenario_note = f"读图：{read_image}。{thesis}".strip()
    if notes:
        scenario_note = (scenario_note + " " + "；".join(notes[:3])).strip()
    return {
        "dates": [d.isoformat() for d in display_dates],
        "board_codes": ordered,
        "board_names": labels,
        "x": dense_x,
        "x_tickvals": [float(i) for i in x_ticks],
        "x_ticktext": labels,
        "z_short": dense_z,
        "z_boards": z_native,
        "axis_note": (
            "看图续气泡：视觉模型读实盘底图 → 输出气泡结构场 → 本系统按叶序重绘。"
            "属结构情景，不是点预测。"
        ),
        "as_of": tip.isoformat(),
        "forecast_dates": [d.isoformat() for d in forecast_dates],
        "context_dates": [d.isoformat() for d in context],
        "board_count": len(ordered),
        "scenario_note": scenario_note,
        "thesis": thesis,
        "empty_message": None,
        "densify": 4,
    }


def run_bubble_field_forecast(
    *,
    tip: date,
    hist: list[date],
    heat_by_day: dict[date, dict[str, float]],
    names: dict[str, str],
    ordered: list[str],
    forecast_dates: list[date],
    ref_dir: Path | None = None,
) -> tuple[dict[str, Any], str, str, str]:
    """Full pipeline. Returns plane, prompt, model_id, ref_png path."""
    ref_dir = ref_dir or Path("experiments/out")
    ref_path = ref_dir / f"industry_heat_ref_{tip.isoformat()}.png"
    ctx_hist = hist[-REF_CONTEXT_DAYS:] if len(hist) >= REF_CONTEXT_DAYS else list(hist)
    render_industry_heat_reference_png(
        tip=tip,
        hist=ctx_hist,
        heat_by_day=heat_by_day,
        names=names,
        ordered=ordered,
        out_path=ref_path,
    )
    template, prompt = build_bubble_forecast_prompt(
        tip=tip, forecast_dates=forecast_dates
    )
    scenario, model_id = call_bubble_vision_llm(
        prompt=prompt, image_path=ref_path, template=template
    )
    plane = build_bubble_forecast_plane(
        tip=tip,
        hist=hist,
        heat_by_day=heat_by_day,
        names=names,
        ordered=ordered,
        forecast_dates=forecast_dates,
        scenario=scenario,
    )
    return plane, prompt, model_id, str(ref_path)
