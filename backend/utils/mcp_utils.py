import json
import re

from .constants import KEYWORDS_LINE_PREFIX


def strip_keywords_line(document: str) -> str:
    """Remove the keywords line NewsDocument embeds in indexed documents —
    it aids retrieval matching but is noise for the reading model."""
    return re.sub(rf"^{re.escape(KEYWORDS_LINE_PREFIX)}.*(?:\n|$)", "", document, flags=re.MULTILINE)


def entities_to_text(entities_json_str):
    try:
        entities = json.loads(entities_json_str)
    except Exception:
        return "- [invalid entities data]"

    lines = []
    for e in entities:
        name = e.get("name", "N/A")
        symbol = e.get("symbol", "N/A")
        sentiment = e.get("sentiment", "N/A")
        industry = e.get("industry", "N/A")
        lines.append(f"- {name} (Symbol: {symbol}), Sentiment: {sentiment}, Industry: {industry}")
    return "\n".join(lines)


def format_metadata(metadata: dict) -> str:
    skip_fields = {"entity_symbols", "entity_names"}

    top_level_lines = []
    for k, v in metadata.items():
        if k in skip_fields or k == "entities":
            continue
        top_level_lines.append(f"{k}: {v}")

    entity_str = ""
    if "entities" in metadata:
        entity_str = "Entities:\n" + entities_to_text(metadata["entities"])

    return "\n".join(top_level_lines + ([entity_str] if entity_str else []))
