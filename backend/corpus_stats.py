import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from statistics import median
from typing import Any
from urllib.parse import urlparse

from backend.config import BACKEND_DIR, CHROMA_DATA_DIR, DB_DIR, RAW_HTML_DIR, config
from backend.data.chroma import ChromaClient
from backend.data.sqlite import MarketNewsDB
from backend.utils import Article, logger, parse_published_at

SQLITE_DB = DB_DIR / "market_news.db"
CHROMA_DIR = CHROMA_DATA_DIR

JSON_OUTPUT = BACKEND_DIR / "corpus_analysis.json"


def sizeof_fmt(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"


def corpus_analysis(json_output: bool = False) -> None:
    db = MarketNewsDB()
    chroma = ChromaClient()

    articles = db.get_articles()

    report = {
        "generated_at": datetime.now().isoformat(),
        "sqlite_article_count": db.count(),
        "chroma_article_count": chroma.count(),
        "ticker_coverage": ticker_coverage_analysis(articles),
        "corpus_statistics": corpus_statistics(articles),
        "storage_statistics": storage_statistics(),
    }

    print_report(report)

    if json_output:
        with JSON_OUTPUT.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print("")
        print(f"JSON report written to {JSON_OUTPUT}")


@dataclass
class _TickerAccumulator:
    count: int = 0
    weekly: Counter = field(default_factory=Counter)
    oldest_dt: datetime | None = None
    oldest: str | None = None
    newest_dt: datetime | None = None
    newest: str | None = None


def ticker_coverage_analysis(articles: list[Article]) -> dict:
    watchlist = set(config.ingestion.symbols)

    stats: defaultdict[str, _TickerAccumulator] = defaultdict(_TickerAccumulator)

    for article in articles:
        dt = parse_published_at(article.published_at)

        for entity in article.entities:
            symbol = entity.symbol

            if symbol not in watchlist:
                continue

            s = stats[symbol]
            s.count += 1

            if dt is None:
                continue

            year, week, _ = dt.isocalendar()
            s.weekly[(year, week)] += 1

            if s.oldest_dt is None or dt < s.oldest_dt:
                s.oldest_dt = dt
                s.oldest = article.published_at

            if s.newest_dt is None or dt > s.newest_dt:
                s.newest_dt = dt
                s.newest = article.published_at

    result: dict[str, dict[str, Any]] = {}

    for symbol in sorted(watchlist):
        acc = stats.get(symbol)

        if acc is None:
            result[symbol] = {
                "count": 0,
                "active_weeks": 0,
                "avg_per_week": 0.0,
                "max_per_week": 0,
                "oldest": None,
                "newest": None,
            }
            continue

        result[symbol] = {
            "count": acc.count,
            "active_weeks": len(acc.weekly),
            "avg_per_week": (sum(acc.weekly.values()) / len(acc.weekly)) if acc.weekly else 0.0,
            "max_per_week": max(acc.weekly.values()) if acc.weekly else 0,
            "oldest": acc.oldest,
            "newest": acc.newest,
        }

    return result


def corpus_statistics(articles: list[Article]) -> dict:
    if not articles:
        return {
            "article_count": 0,
            "text_lengths": {
                "min": 0,
                "median": 0,
                "average": 0.0,
                "p95": 0,
                "max": 0,
                "under_300": 0,
                "under_300_pct": 0.0,
                "empty": 0,
                "empty_pct": 0.0,
            },
            "status_distribution": {},
            "domain_distribution": {},
        }

    lengths = []

    empty_count = 0
    under_300_count = 0

    status_counts: Counter[str | None] = Counter()
    domain_counts: Counter[str] = Counter()

    for article in articles:
        text = article.full_text or ""

        length = len(text)

        lengths.append(length)

        if length == 0:
            empty_count += 1

        if length < 300:
            under_300_count += 1

        status_counts[article.full_text_status] += 1

        domain = urlparse(article.url).netloc.lower()

        if domain.startswith("www."):
            domain = domain[4:]

        domain_counts[domain] += 1

    sorted_lengths = sorted(lengths)

    return {
        "article_count": len(lengths),
        "text_lengths": {
            "min": min(lengths),
            "median": median(lengths),
            "average": sum(lengths) / len(lengths),
            "p95": sorted_lengths[int(0.95 * len(sorted_lengths))],
            "max": max(lengths),
            "under_300": under_300_count,
            "under_300_pct": 100 * under_300_count / len(lengths),
            "empty": empty_count,
            "empty_pct": 100 * empty_count / len(lengths),
        },
        "status_distribution": dict(status_counts),
        "domain_distribution": dict(domain_counts),
    }

def storage_statistics() -> dict:
    sqlite: dict[str, Any] = {
        "exists": SQLITE_DB.exists(),
        "size_bytes": 0,
        "size_human": None,
    }

    if sqlite["exists"]:
        sqlite["size_bytes"] = SQLITE_DB.stat().st_size
        sqlite["size_human"] = sizeof_fmt(sqlite["size_bytes"])

    chroma: dict[str, Any] = {
        "exists": CHROMA_DIR.exists(),
        "size_bytes": 0,
        "size_human": None,
        "file_count": 0,
    }

    if chroma["exists"]:
        chroma_files = [f for f in CHROMA_DIR.rglob("*") if f.is_file()]

        chroma["file_count"] = len(chroma_files)
        chroma["size_bytes"] = sum(f.stat().st_size for f in chroma_files)
        chroma["size_human"] = sizeof_fmt(chroma["size_bytes"])

    raw_html: dict[str, Any] = {
        "exists": RAW_HTML_DIR.exists(),
        "file_count": 0,
        "total_size_bytes": 0,
        "total_size_human": None,
        "average_size_bytes": 0,
        "average_size_human": None,
    }

    if raw_html["exists"]:
        html_files = [f for f in RAW_HTML_DIR.rglob("*") if f.is_file()]

        raw_html["file_count"] = len(html_files)
        raw_html["total_size_bytes"] = sum(
            f.stat().st_size for f in html_files
        )

        raw_html["total_size_human"] = sizeof_fmt(
            raw_html["total_size_bytes"]
        )

        if html_files:
            raw_html["average_size_bytes"] = (
                raw_html["total_size_bytes"] // len(html_files)
            )

            raw_html["average_size_human"] = sizeof_fmt(
                raw_html["average_size_bytes"]
            )

    return {
        "sqlite": sqlite,
        "chroma": chroma,
        "raw_html": raw_html,
    }


def print_report(report: dict) -> None:
    print("=" * 120)
    print("Corpus analysis")
    print("=" * 120)

    print(
        f"SQLite articles: {report['sqlite_article_count']}"
    )

    print(
        f"Chroma articles: {report['chroma_article_count']}"
    )

    print("")

    print_ticker_coverage(report["ticker_coverage"])

    print("")

    print_corpus_statistics(report["corpus_statistics"])

    print("")

    print_storage_statistics(report["storage_statistics"])


def print_ticker_coverage(data: dict) -> None:
    print("=" * 120)
    print("Ticker coverage")
    print("=" * 120)

    for symbol, stats in data.items():
        if stats["count"] == 0:
            print(f"{symbol:6} | No articles found")
            continue

        print(
            f"{symbol:6} | "
            f"Count: {stats['count']:4} | "
            f"Active weeks: {stats['active_weeks']:2} | "
            f"Avg/week: {stats['avg_per_week']:5.2f} | "
            f"Max/week: {stats['max_per_week']:2} | "
            f"Oldest: {stats['oldest']} | "
            f"Newest: {stats['newest']}"
        )


def print_corpus_statistics(data: dict) -> None:
    text = data["text_lengths"]

    print("=" * 120)
    print("Full text statistics")
    print("=" * 120)

    print(f"Articles:               {data['article_count']}")
    print(f"Min length:             {text['min']} chars")
    print(f"Median length:          {text['median']:.0f} chars")
    print(f"Average length:         {text['average']:.2f} chars")
    print(f"95th percentile:        {text['p95']} chars")
    print(f"Max length:             {text['max']} chars")

    print(
        f"Under 300 chars:        {text['under_300']} "
        f"({text['under_300_pct']:.1f}%)"
    )

    print(
        f"Empty texts:            {text['empty']} "
        f"({text['empty_pct']:.1f}%)"
    )

    print("")
    print("Full text status distribution:")

    total = data["article_count"]

    for status, count in sorted(
        data["status_distribution"].items(),
        key=lambda x: x[1],
        reverse=True,
    ):
        print(
            f"  {status:<12}: {count:4} "
            f"({100 * count / total:5.1f}%)"
        )

    print("")
    print("=" * 120)
    print("Domain distribution")
    print("=" * 120)

    for domain, count in sorted(
        data["domain_distribution"].items(),
        key=lambda x: x[1],
        reverse=True,
    ):
        print(
            f"{domain:<40} "
            f"{count:4} "
            f"({100 * count / total:5.1f}%)"
        )

def print_storage_statistics(data: dict) -> None:
    print("=" * 120)
    print("Storage statistics")
    print("=" * 120)

    sqlite = data["sqlite"]

    if sqlite["exists"]:
        print(
            f"SQLite database:        {sqlite['size_human']}"
        )
    else:
        logger.warning("SQLite database not found.")

    chroma = data["chroma"]

    if chroma["exists"]:
        print(
            f"Chroma database:        {chroma['size_human']}"
        )
        print(
            f"Chroma files:           {chroma['file_count']}"
        )
    else:
        logger.warning("Chroma database not found.")

    raw_html = data["raw_html"]

    if raw_html["exists"]:
        print(
            f"Raw HTML files:         {raw_html['file_count']}"
        )
        print(
            f"Raw HTML total size:    {raw_html['total_size_human']}"
        )
        print(
            f"Average HTML size:      {raw_html['average_size_human']}"
        )
    else:
        logger.warning("Raw HTML directory not found.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze the FinanceWatcher corpus."
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Also export the report as corpus_analysis.json",
    )

    args = parser.parse_args()

    corpus_analysis(json_output=args.json)


if __name__ == "__main__":
    main()