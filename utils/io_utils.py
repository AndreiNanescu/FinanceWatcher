import os
import re
import json
import logging

from pathlib import Path
from typing import Union

def save_dict_as_json(data: dict, filepath: Union[str, Path]):
    logger = logging.getLogger(__name__)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    logger.info(f"Saved data to {filepath}")


def normalize_name(name: str) -> str:
    if not name:
        return ""
    name = name.lower()
    name = re.sub(r"\b(inc|inc\.|ltd|ltd\.|corp|corp\.|llc|llc\.)\b", "", name)
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", "_", name).strip()
    return name