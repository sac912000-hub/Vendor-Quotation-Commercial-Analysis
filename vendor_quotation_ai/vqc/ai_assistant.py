"""Claude layer: writes the executive summary and answers questions.

Design rule: Python computes every number (analysis.py). Claude only *explains* them, using the
compact JSON in `facts`, so it cannot invent prices. Works only if ANTHROPIC_API_KEY is set.
"""
from __future__ import annotations
import json
import os

DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")

SYSTEM = """You are a senior procurement analyst helping a buyer at a steel plant evaluate vendor quotations.
You are given FACTS_JSON computed by a deterministic Python engine. Rules:
- Use ONLY numbers that appear in FACTS_JSON. Never invent or estimate prices, dates or percentages.
  If something is not in the data, say it is not available.
- Currency is INR. Show large amounts in crore (1 Cr = 10,000,000) with 2 decimals.
- Landed-cost percentages are placeholder assumptions: mention that when the comparison basis is not 'quoted'.
- Partial quotes (coverage < 100%) are not directly comparable with full-scope quotes.
- Be concrete, concise and decision-oriented. Prefer short paragraphs and tight bullet lists.
FACTS_JSON:
{facts}
"""

SUMMARY_PROMPT = """Write an executive summary for the purchase committee with these sections:
1. Recommendation (one vendor or a split award, and why, in 3-4 sentences)
2. Price position (who is L1 overall and item-wise, gaps in %)
3. Commercial and delivery trade-offs (payment risk, delivery, warranty, supervision)
4. Red flags to resolve before award
5. Negotiation levers and next steps (specific vendor/item actions, max 5 bullets)
Keep it under 350 words."""


def available(api_key: str | None = None) -> bool:
    return bool(api_key or os.getenv("ANTHROPIC_API_KEY"))


def _call(system: str, messages: list[dict], api_key: str | None, model: str | None, max_tokens: int = 1500) -> str:
    import anthropic  # imported lazily so the rest of the app works without the package
    client = anthropic.Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
    resp = client.messages.create(model=model or DEFAULT_MODEL, max_tokens=max_tokens,
                                  system=system, messages=messages)
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def executive_summary(facts: dict, api_key: str | None = None, model: str | None = None) -> str:
    system = SYSTEM.format(facts=json.dumps(facts, default=str))
    return _call(system, [{"role": "user", "content": SUMMARY_PROMPT}], api_key, model)


def ask(question: str, facts: dict, history: list[dict] | None = None,
        api_key: str | None = None, model: str | None = None) -> str:
    system = SYSTEM.format(facts=json.dumps(facts, default=str))
    msgs = [m for m in (history or []) if m["role"] in ("user", "assistant")]
    msgs.append({"role": "user", "content": question})
    return _call(system, msgs, api_key, model)
