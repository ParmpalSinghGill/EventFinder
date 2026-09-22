"""
Scrape the first Moneycontrol 'Stocks To Watch' article link, extract the
company names mentioned there, and write the last matching NSE symbol.

Output format:
    data/screener_output/MC_YYYYMMDD_HHMMSS.txt

Usage:
    conda run -n STOCK python scrape_moneycontrol_stocks.py
    conda run -n STOCK python scrape_moneycontrol_stocks.py --date 20260704
"""

import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


import argparse
import os
import re
from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd
import requests
from bs4 import BeautifulSoup

from stock.ticker_mapping import find_symbols_from_text, load_catalog
import stock.watchlist_utils as watchlist_utils

BASE = _ROOT
DATA_DIR = BASE / "stock" / "data"
MASTER_CSV = DATA_DIR / "nse_equity_list.csv"
OUTDIR = DATA_DIR / "screener_output"
URL = "https://www.moneycontrol.com/news/tags/stocks-to-watch.html"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

STOPWORDS = {
    "and",
    "for",
    "the",
    "with",
    "into",
    "from",
    "that",
    "this",
    "their",
    "have",
    "been",
    "will",
    "about",
    "after",
    "over",
    "under",
    "more",
    "less",
    "than",
    "when",
    "where",
    "your",
    "our",
    "are",
    "was",
    "were",
    "can",
    "not",
    "but",
    "also",
    "today",
    "stock",
    "stocks",
    "news",
    "watch",
    "market",
    "share",
    "shares",
    "company",
    "companies",
    "limited",
    "ltd",
    "corp",
    "corporation",
    "group",
    "holdings",
    "services",
    "technologies",
    "technology",
    "finance",
    "financial",
}


def parse_target_date(value: str | None) -> datetime:
    if not value:
        return datetime.now()

    text = (value or "").strip()
    if not text:
        return datetime.now()

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    slash_match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?", text)
    if slash_match:
        day = int(slash_match.group(1))
        month = int(slash_match.group(2))
        year_text = slash_match.group(3)
        if year_text is None:
            year = datetime.now().year
        else:
            year = int(year_text)
            if len(year_text) == 2:
                year = 2000 + year if year < 70 else 1900 + year
        if 1 <= month <= 12 and 1 <= day <= 31:
            return datetime(year, month, day)

    month_match = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)(?:\s+(\d{2,4}))?", text)
    if month_match:
        day = int(month_match.group(1))
        month_name = month_match.group(2).lower()
        month_map = {
            "jan": 1,
            "january": 1,
            "feb": 2,
            "february": 2,
            "mar": 3,
            "march": 3,
            "apr": 4,
            "april": 4,
            "may": 5,
            "jun": 6,
            "june": 6,
            "jul": 7,
            "july": 7,
            "aug": 8,
            "august": 8,
            "sep": 9,
            "sept": 9,
            "september": 9,
            "oct": 10,
            "october": 10,
            "nov": 11,
            "november": 11,
            "dec": 12,
            "december": 12,
        }
        month = month_map.get(month_name)
        if month is not None and 1 <= day <= 31:
            year = int(month_match.group(3)) if month_match.group(3) else datetime.now().year
            if len(str(year)) == 2:
                year = 2000 + year if year < 70 else 1900 + year
            return datetime(year, month, day)

    raise ValueError("Date must be YYYY-MM-DD, YYYYMMDD, DD/MM, DD/MM/YY, or DD month name")


def is_article_candidate_link(href: str) -> bool:
    low = (href or "").strip().lower()
    if not low or "/news/" not in low:
        return False
    if "moneycontrol.com/news/tags/" in low:
        return False
    if low.endswith("/"):
        return False
    return ".html" in low or "/videos/" in low or "/photos/" in low or "/blogs/" in low


def find_first_article_link(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        text = " ".join(a.stripped_strings).strip()
        if not href or not text:
            continue
        if is_article_candidate_link(href):
            return href
    return None


def find_article_link_for_date(html: str, target_dt: datetime) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    day = target_dt.strftime("%d")
    day_no_zero = day.lstrip("0") or "0"
    month_names = {
        target_dt.strftime("%B").lower(),
        target_dt.strftime("%b").lower(),
    }
    date_tokens = {
        target_dt.strftime("%d %B"),
        target_dt.strftime("%d %b"),
        target_dt.strftime("%d-%B").lower(),
        target_dt.strftime("%d-%b").lower(),
        target_dt.strftime("%d/%m"),
        target_dt.strftime("%d-%m"),
        day,
        day_no_zero,
    }
    date_tokens.update({f"{day} {month}" for month in month_names})
    date_tokens.update({f"{day_no_zero} {month}" for month in month_names})
    date_tokens.update({f"{day}-{month}" for month in month_names})
    date_tokens.update({f"{day_no_zero}-{month}" for month in month_names})
    date_tokens.update({f"{day}/{month}" for month in month_names})
    date_tokens.update({f"{day_no_zero}/{month}" for month in month_names})
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        text = " ".join(a.stripped_strings).strip()
        if not href or not text:
            continue
        if not is_article_candidate_link(href):
            continue
        combined = f"{text} {href}".lower()
        has_day_month = any(token.lower() in combined for token in date_tokens if " " in token or "-" in token or "/" in token)
        has_month_only = any(token in combined for token in month_names)
        if has_day_month or (day in combined and has_month_only) or (day_no_zero in combined and has_month_only):
            return href
    return find_first_article_link(html)


def extract_article_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        return str(og_title["content"]).strip()

    if soup.title and soup.title.string:
        return str(soup.title.string).strip()

    for tag in soup.find_all(["h1", "h2"]):
        text = " ".join(tag.stripped_strings).strip()
        if text:
            return text
    return ""


def extract_article_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    blocks = []

    title = extract_article_title(html)
    if title:
        blocks.append(title)

    for tag in soup.find_all(["article", "p", "h1", "h2", "h3", "li", "div", "span"]):
        text = " ".join(tag.stripped_strings).strip()
        if text and 3 <= len(text) <= 300:
            blocks.append(text)
    return "\n".join(blocks)


def build_manual_review_text(article_title: str, article_link: str, symbols: List[str], missing_names: List[str]) -> str:
    lines = []
    if article_title:
        lines.append(article_title)
    lines.append("")
    lines.append("Read More:")
    if article_link:
        lines.append(article_link)
    if symbols:
        lines.append("")
        lines.append("Mapped tickers:")
        lines.append(",".join(symbols))
    if missing_names:
        lines.append("")
        lines.append("No ticker found:")
        lines.append("\n".join(missing_names))
    return "\n".join(lines)


def write_failure_outputs(out_dir: Path, target_dt: datetime, error_text: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = target_dt.strftime("%Y%m%d")
    review_path = out_dir / f"MC_review_{stamp}.txt"
    latest_review_path = out_dir / "latest_MC_review.txt"
    missing_path = out_dir / f"MC_missing_{stamp}.txt"
    latest_missing_path = out_dir / "latest_MC_missing.txt"
    missing_csv_path = out_dir / f"MC_missing_{stamp}.csv"
    latest_missing_csv_path = out_dir / "latest_MC_missing.csv"

    review_text = f"Moneycontrol scrape failed.\n\nError:\n{error_text}"
    review_path.write_text(review_text, encoding="utf-8")
    latest_review_path.write_text(review_text, encoding="utf-8")
    missing_path.write_text("", encoding="utf-8")
    latest_missing_path.write_text("", encoding="utf-8")
    missing_csv_path.write_text("Name\n", encoding="utf-8")
    latest_missing_csv_path.write_text("Name\n", encoding="utf-8")

    # Sync and clean
    watchlist_utils.sync_and_clean_watchlist("latest_MC_missing.txt", "")


def export_fyers_watchlist(symbols: List[str], target_dt: datetime, article_title: str, article_link: str, missing_names: List[str]) -> None:
    export_dir = Path(watchlist_utils.get_export_dir())
    export_dir.mkdir(parents=True, exist_ok=True)

    fyers_symbols = [f"NSE:{symbol}-EQ" for symbol in symbols]
    stamp = target_dt.strftime("%Y%m%d")
    txt_path = export_dir / f"MC_fyers_{stamp}.txt"
    csv_path = export_dir / f"MC_fyers_{stamp}.csv"
    latest_txt_path = export_dir / "latest_MC_fyers.txt"
    latest_csv_path = export_dir / "latest_MC_fyers.csv"
    review_txt_path = export_dir / f"MC_review_{stamp}.txt"
    review_latest_txt_path = export_dir / "latest_MC_review.txt"
    missing_txt_path = export_dir / f"MC_missing_{stamp}.txt"
    missing_latest_txt_path = export_dir / "latest_MC_missing.txt"
    missing_csv_path = export_dir / f"MC_missing_{stamp}.csv"
    missing_latest_csv_path = export_dir / "latest_MC_missing.csv"

    review_text = build_manual_review_text(article_title, article_link, symbols, missing_names)
    missing_text = "\n".join(missing_names)

    txt_path.write_text(",".join(fyers_symbols), encoding="ascii")
    csv_path.write_text("Symbol\n" + "\n".join(fyers_symbols), encoding="ascii")
    latest_txt_path.write_text(",".join(fyers_symbols), encoding="ascii")
    latest_csv_path.write_text("Symbol\n" + "\n".join(fyers_symbols), encoding="ascii")
    review_txt_path.write_text(review_text, encoding="utf-8")
    review_latest_txt_path.write_text(review_text, encoding="utf-8")
    missing_txt_path.write_text(missing_text, encoding="utf-8")
    missing_latest_txt_path.write_text(missing_text, encoding="utf-8")
    missing_csv_path.write_text("Name\n" + "\n".join(missing_names), encoding="utf-8")
    missing_latest_csv_path.write_text("Name\n" + "\n".join(missing_names), encoding="utf-8")

    # Sync only latest_MC_fyers.txt and latest_MC_missing.txt to ~/Downloads/Watchlist, and clean up.
    watchlist_utils.sync_and_clean_watchlist("latest_MC_fyers.txt", ",".join(fyers_symbols))
    watchlist_utils.sync_and_clean_watchlist("latest_MC_missing.txt", missing_text)

    print(f"Exported Fyers watchlist -> {txt_path}")
    print(f"Exported Fyers CSV -> {csv_path}")
    print(f"Exported review text -> {review_txt_path}")
    print(f"Exported missing names -> {missing_txt_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Moneycontrol stocks-to-watch article")
    parser.add_argument("--date", help="Optional date to target (YYYY-MM-DD or YYYYMMDD)")
    args = parser.parse_args()

    target_dt = parse_target_date(args.date)

    # Skip weekends if running scheduled (auto) mode (i.e. no explicit date passed)
    if not args.date and target_dt.weekday() >= 5:
        print(f"Moneycontrol @ {target_dt.strftime('%Y-%m-%d')}: weekend, skipping scrape.")
        return

    OUTDIR.mkdir(parents=True, exist_ok=True)
    print(f"Parsed date: {target_dt.strftime('%Y-%m-%d')}")

    try:
        response = requests.get(URL, headers=HEADERS, timeout=30)
        response.raise_for_status()

        first_link = find_article_link_for_date(response.text, target_dt)
        if not first_link:
            raise RuntimeError("Could not find a suitable article link on the page")

        article_response = requests.get(first_link, headers=HEADERS, timeout=30)
        article_response.raise_for_status()

        catalog = load_catalog()
        article_title = extract_article_title(article_response.text)
        mapped_pairs = find_symbols_from_text(article_title, catalog)
        symbols = [ticker for _, ticker in mapped_pairs if ticker]
        missing_names = [name for name, ticker in mapped_pairs if not ticker]
        symbol = symbols[-1] if symbols else ""
        ticker_text = ",".join(symbols)

        stamp = target_dt.strftime("%Y%m%d")
        out_path = OUTDIR / f"MC_{stamp}.txt"
        latest_path = OUTDIR / "latest_mc.txt"

        review_text = build_manual_review_text(article_title, first_link, symbols, missing_names)
        with out_path.open("w", encoding="utf-8") as f:
            f.write(review_text)
        with latest_path.open("w", encoding="utf-8") as f:
            f.write(review_text)

        export_fyers_watchlist(symbols, target_dt, article_title, first_link, missing_names)

        print(f"First article link: {first_link}")
        print(f"Original page title: {article_title}")
        print("\n\n","*"*50)
        print("Mapped name -> ticker pairs:")
        for name, ticker in mapped_pairs:
            print(f"  - {name} -> {ticker or '<NO MATCH>'}")
        print(f"\nTicker list: {symbols}")
        print(f"Selected last symbol: {symbol}")
        print(f"Full ticker list written: {symbols}")
        print(f"Saved -> {out_path}")
        print(f"Latest -> {latest_path}")
    except Exception as exc:  # pragma: no cover - defensive batch-run behavior
        stamp = target_dt.strftime("%Y%m%d")
        out_path = OUTDIR / f"MC_{stamp}.txt"
        latest_path = OUTDIR / "latest_mc.txt"
        out_path.write_text(f"Moneycontrol scrape failed.\nError: {exc}", encoding="utf-8")
        latest_path.write_text(f"Moneycontrol scrape failed.\nError: {exc}", encoding="utf-8")
        write_failure_outputs(Path(watchlist_utils.get_export_dir()), target_dt, str(exc))
        print(f"Moneycontrol scrape failed: {exc}")
        print(f"Saved failure notice -> {out_path}")


if __name__ == "__main__":
    main()
