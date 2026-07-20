"""Deterministic core of utils plus the scraper's bot-page detector."""

from backend.data_pipeline.gatherers.scraper.stealth_scraper import looks_like_bot_page
from backend.utils import format_sentiment, normalize_name, save_raw_html, symbol_flag_key


def test_symbol_flag_key_sanitizes_ticker_punctuation():
    assert symbol_flag_key("AAPL") == "sym_AAPL"
    assert symbol_flag_key(" hdb.ba ") == "sym_HDB_BA"
    assert symbol_flag_key("^NSEI") == "sym__NSEI"


def test_normalize_name_strips_case_punctuation_and_suffixes():
    assert normalize_name("Apple Inc.") == "apple"
    assert normalize_name("Microsoft Corporation") == "microsoft"
    assert normalize_name("BlackRock, Inc.") == "blackrock"


def test_format_sentiment_boundaries():
    assert format_sentiment(0.21) == "Positive (0.21)"
    assert format_sentiment(0.20) == "Neutral (0.20)"  # threshold is strictly greater
    assert format_sentiment(-0.20) == "Neutral (-0.20)"
    assert format_sentiment(-0.21) == "Negative (-0.21)"


def test_save_raw_html_writes_sanitized_filename(tmp_path):
    save_raw_html("weird/uuid:1", "<html>x</html>", base_dir=tmp_path)
    files = list(tmp_path.glob("*.html"))
    assert len(files) == 1
    assert files[0].name == "weird_uuid_1.html"
    assert files[0].read_text(encoding="utf-8") == "<html>x</html>"


def test_save_raw_html_ignores_empty_html(tmp_path):
    save_raw_html("u1", "", base_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_bot_page_strong_markers_always_flag():
    assert looks_like_bot_page("Visitors may be misidentified as bots due to disabled JavaScript.")
    assert looks_like_bot_page("Checking your browser before accessing the site. " * 200)  # length-proof


def test_bot_page_weak_markers_flag_only_short_texts():
    short = "Please enable JavaScript and cookies to continue."
    long_article = ("Apple reported strong quarterly revenue growth driven by services. " * 60) + short
    assert looks_like_bot_page(short)
    assert not looks_like_bot_page(long_article)


def test_bot_page_clean_text_passes():
    assert not looks_like_bot_page("Apple shares rose 3% after earnings beat expectations.")
    assert not looks_like_bot_page(None)
    assert not looks_like_bot_page("")
