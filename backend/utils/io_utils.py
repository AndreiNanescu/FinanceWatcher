import json
import os
import re
from pathlib import Path

from .logger import logger

RAW_HTML_DIR = Path(__file__).resolve().parent.parent / "data" / "raw_html"


def save_raw_html(uuid: str, html: str, base_dir: str | Path | None = None) -> None:
    """Archive an article's raw HTML keyed by its uuid. Never fatal — the
    archive is insurance, not a pipeline dependency."""
    if not html:
        return
    try:
        base = Path(base_dir) if base_dir else RAW_HTML_DIR
        base.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^\w.-]", "_", uuid)
        (base / f"{safe_name}.html").write_text(html, encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to archive raw HTML for {uuid}: {e}")


def save_dict_as_json(data: dict, filepath: str | Path):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    logger.info(f"Saved data to {filepath}")


def normalize_name(name: str) -> str:
    import re

    name = name.lower()

    name = re.sub(r"[^\w\s]", "", name)
    suffixes = [
        " corporation",
        " corp",
        " incorporated",
        " inc",
        " ltd",
        " limited",
        " co",
        " group",
        " llc",
        " company",
        " technologies",
        " services",
        " ai",
        "com",
    ]
    for suffix in suffixes:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    name = " ".join(name.split())
    return name


def log_args(args_dict):
    args_str = " | ".join(f"{k}={v}" for k, v in args_dict.items() if v is not None)
    if args_str:
        logger.info(f"Starting data pipeline with: {args_str}")
