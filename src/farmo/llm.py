"""Optional LLM fallback for names the regex parser can't handle. Off unless `farmo normalize --llm`.

Requires `uv sync --extra llm` and Anthropic credentials (ANTHROPIC_API_KEY or `ant auth login`).
Model defaults to claude-opus-5-5 at low effort; override with FARMO_LLM_MODEL.
"""

import json
import logging
import os

log = logging.getLogger("farmo.llm")

MODEL = os.environ.get("FARMO_LLM_MODEL", "claude-opus-5-5")
BATCH = 40

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "ingredients": {"type": "array", "items": {"type": "string"},
                                    "description": "active ingredients, lowercase Spanish INN without accents or salts, e.g. 'losartan', 'hidroclorotiazida'"},
                    "strengths": {"type": "array", "items": {"type": "number"},
                                  "description": "one strength per ingredient, same order"},
                    "unit": {"type": ["string", "null"], "description": "mg, mcg, ui, mg/ml, % ..."},
                    "form": {"type": ["string", "null"],
                             "description": "comprimido, capsula, jarabe, suspension, gotas, inhalador, inyectable, topico, sobre, solucion"},
                    "pack_size": {"type": ["number", "null"], "description": "units or ml in the package"},
                    "pack_unit": {"type": ["string", "null"], "description": "unidad | ml | dosis"},
                },
                "required": ["id", "ingredients", "strengths", "unit", "form", "pack_size", "pack_unit"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

PROMPT = """You parse Paraguayan pharmacy product listings. For each item, extract the active ingredient(s),
strength(s), form and pack size. Brand names (e.g. CONVERTAL, HIPERCOR) hide the ingredient: use your
pharmaceutical knowledge and the description if given. If you are not reasonably sure, return an empty
ingredients list rather than guessing. "X 10 TIRAS" means 10 strips of unknown size: pack_size null.

Items (JSON):
"""


def parse_batch(items: list[dict]) -> dict[int, dict]:
    """items: [{'id', 'name', 'description'}] -> {id: parsed}"""
    import anthropic  # optional dependency

    client = anthropic.Anthropic()
    out: dict[int, dict] = {}
    for i in range(0, len(items), BATCH):
        chunk = items[i:i + BATCH]
        try:
            resp = client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                messages=[{"role": "user", "content": PROMPT + json.dumps(chunk, ensure_ascii=False)}],
            )
        except anthropic.APIStatusError as e:
            log.error("LLM batch failed (%s): %s", e.status_code, e.message)
            continue
        except anthropic.APIConnectionError as e:
            log.error("LLM connection error: %s", e)
            continue
        if resp.stop_reason in ("refusal", "max_tokens"):
            log.warning("LLM batch stopped: %s", resp.stop_reason)
            continue
        text = next((b.text for b in resp.content if b.type == "text"), "{}")
        for it in json.loads(text).get("items", []):
            out[it["id"]] = it
    return out
