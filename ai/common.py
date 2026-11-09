"""Shared helpers for the AI scripts: read-only database access, the Claude call, and the number check.

The API key is read from the environment (ANTHROPIC_API_KEY), loaded from a local .env file that git ignores.
It is never written in the code. Without a key, the scripts run in OFFLINE mode (templates, no LLM).
"""
import json
import os
import re
from pathlib import Path

import sys

import duckdb

if hasattr(sys.stdout, "reconfigure"):      # Windows consoles default to cp1252
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "commercial.duckdb"
PROMPTS = ROOT / "ai" / "prompts"
MODEL = "claude-opus-5-5"

try:                                    # .env is optional: an exported environment variable works too
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def has_api_key():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


# ---------------------------------------------------------------- database
def connect_read_only():
    """Read-only connection with external file / network access disabled: generated SQL can only read the model tables."""
    return duckdb.connect(str(DB), read_only=True, config={"enable_external_access": False})


def query_df(sql, con=None):
    own = con is None
    con = con or connect_read_only()
    try:
        return con.execute(sql).df()
    finally:
        if own:
            con.close()


# ---------------------------------------------------------------- LLM
_client = None


def call_claude(system, user, schema=None, effort="medium", max_tokens=16000):
    """One Messages API call. `schema` (JSON schema) turns on structured output: the reply is then valid JSON.
    Returns (text, usage dict). Raises RuntimeError on a refusal so the caller can fall back to its offline path."""
    global _client
    import anthropic
    if _client is None:
        _client = anthropic.Anthropic()          # reads ANTHROPIC_API_KEY from the environment
    output_config = {"effort": effort}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    resp = _client.beta.messages.create(
        model=MODEL, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
        output_config=output_config,
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",   # a declined request is re-run on a fallback model
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"model declined the request ({getattr(resp.stop_details, 'category', None)})")
    text = "".join(b.text for b in resp.content if b.type == "text")
    usage = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens, "model": resp.model}
    return text, usage


def load_prompt(name):
    return (PROMPTS / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- number check (grounding)
# A number in the text is "supported" only if the same value appears in the facts the model was given.
# Account ids (FR-054) and ISO month keys are removed first so their digits are not read as figures.
ID_PATTERN = re.compile(r"\b[A-Z]{2}-\d{3}\b")
NUM_PATTERN = re.compile(r"(?<![\w.])[-+−]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])[-+−]?\d+(?:\.\d+)?")


def extract_numbers(text):
    text = ID_PATTERN.sub(" ", text)
    out = []
    for m in NUM_PATTERN.finditer(text):
        raw = m.group(0)
        out.append((raw, float(raw.replace(",", "").replace("−", "-").replace("+", ""))))
    return out


def allowed_numbers(facts):
    """Every number present in the facts: numeric leaves and numbers written inside string leaves."""
    vals = set()

    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            vals.add(round(abs(float(x)), 6))
        elif isinstance(x, str):
            for _, v in extract_numbers(x):
                vals.add(round(abs(v), 6))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
    walk(facts)
    return vals


def check_numbers(text, facts):
    """Returns (numbers cited, unsupported numbers). Signs are ignored ('-5.4%' and 'down 5.4%' are the same fact)."""
    allowed = allowed_numbers(facts)
    cited = extract_numbers(text)
    unsupported = [raw for raw, v in cited if round(abs(v), 6) not in allowed]
    return cited, unsupported


def to_json(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)
