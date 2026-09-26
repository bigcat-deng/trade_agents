"""Fill the industry heat-rotation prompt and send it when a model key is set."""

from __future__ import annotations

import argparse
import sys

from app.interpret.service import interpret


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build the industry heat-rotation prompt from the latest 20 trading days. "
            "Sends it only when base URL, model, and API key are set "
            "(prompt frontmatter, or LLM_BASE_URL / LLM_MODEL / LLM_API_KEY)."
        )
    )
    parser.add_argument(
        "--print-prompt",
        action="store_true",
        help="Print the filled prompt",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = interpret("industry-heat-rotation")
        print(
            f"template={result.template} as_of={result.as_of.isoformat()} "
            f"model={result.model} cached={result.cached}",
            flush=True,
        )
        if args.print_prompt:
            from app.interpret.industry_heat import build_industry_heat_prompt

            _template, prompt, _as_of, _latest, _summaries = build_industry_heat_prompt()
            print(prompt, flush=True)
        print(result.content, flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI exit boundary
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
