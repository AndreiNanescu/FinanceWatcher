import os
import json

from pathlib import Path
from typing import Union

from .logger import logger


def save_dict_as_json(data: dict, filepath: Union[str, Path]):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    logger.info(f"Saved data to {filepath}")


def normalize_name(name: str) -> str:
    import re
    name = name.lower()

    name = re.sub(r'[^\w\s]', '', name)
    suffixes = [' corporation', ' corp', ' incorporated', ' inc', ' ltd', ' limited', ' co']
    for suffix in suffixes:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    name = ' '.join(name.split())
    return name

def log_args(args_dict):
    args_str = " | ".join(f"{k}={v}" for k, v in args_dict.items() if v is not None)
    if args_str:
        logger.info(f"Starting data pipeline with: {args_str}")