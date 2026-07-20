from datetime import datetime

from .constants import PUBLISHED_AT_FORMATS
from .logger import logger


def parse_published_at(published_at_str: str | None) -> datetime | None:
    """Parse a published_at string in any known wire format; None if unparseable.

    The single parsing path for article timestamps — retrieval filtering,
    recency scoring, and exports must all agree on what a date string means.
    """
    if not published_at_str:
        return None
    for fmt in PUBLISHED_AT_FORMATS:
        try:
            return datetime.strptime(published_at_str, fmt)
        except ValueError:
            continue
    logger.debug(f"Failed to parse date {published_at_str}")
    return None
