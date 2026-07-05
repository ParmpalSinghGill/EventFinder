from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
MASTER_CSV = DATA_DIR / "nse_equity_list.csv"

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
    "bank",
    "banks",
    "inc",
    "plc",
}


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def build_search_terms(name: str) -> List[str]:
    cleaned = re.sub(
        r"\b(limited|ltd|private|public|corporation|corp|company|co|group|holdings|services|technologies|technology|finance|financial)\b",
        "",
        name,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    terms = []
    if cleaned:
        terms.append(normalize(cleaned))
        terms.append(normalize(name))
    tokens = [tok for tok in re.split(r"[^a-z0-9]+", cleaned.lower()) if len(tok) > 2 and tok not in STOPWORDS]
    terms.extend(tokens)
    return [t for t in terms if t]


def _canonical_tokens(text: str) -> List[str]:
    cleaned = re.sub(
        r"\b(limited|ltd|private|public|corporation|corp|company|co|group|holdings|services|technologies|technology|finance|financial)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    tokens = [
        token
        for token in re.split(r"[^a-z0-9]+", cleaned.lower())
        if len(token) > 2 and token not in STOPWORDS
    ]
    if "sfb" in tokens:
        tokens.extend(["small", "finance", "bank"])
    return tokens


def load_catalog(csv_path: Optional[Path] = None) -> List[dict]:
    path = csv_path or MASTER_CSV
    if not path.exists():
        raise FileNotFoundError(f"Master list not found: {path}")

    df = pd.read_csv(path)
    df = df[df.get("SERIES", "").astype(str).str.upper() == "EQ"].copy()
    df = df[["SYMBOL", "NAME OF COMPANY"]].dropna()
    catalog = []
    for _, row in df.iterrows():
        symbol = str(row["SYMBOL"]).strip().upper()
        name = str(row["NAME OF COMPANY"]).strip()
        if not symbol or not name:
            continue
        catalog.append({"symbol": symbol, "name": name, "terms": build_search_terms(name)})
    return catalog


def extract_title_candidates(text: str) -> List[str]:
    if not text:
        return []

    cleaned = text.strip()
    cleaned = re.sub(r"^.*?stocks to watch today\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bin focus\b.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\btoday\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" :,-")
    if not cleaned:
        return []

    parts = re.split(r",|\band\b", cleaned, flags=re.IGNORECASE)
    candidates = []
    for part in parts:
        candidate = re.sub(r"^[-:]\s*", "", part).strip()
        candidate = candidate.strip(" :,-")
        if candidate and len(candidate.split()) <= 6:
            candidates.append(candidate)
    return candidates


def match_company_to_symbol(candidate: str, catalog: List[dict]) -> str:
    candidate_norm = normalize(candidate)
    if not candidate_norm:
        return ""

    for entry in catalog:
        name_norm = normalize(entry["name"])
        if name_norm and (candidate_norm == name_norm or name_norm in candidate_norm or candidate_norm in name_norm):
            return entry["symbol"]

    candidate_tokens = set(_canonical_tokens(candidate))
    if not candidate_tokens:
        return ""

    best_symbol = ""
    best_score = 0
    for entry in catalog:
        entry_tokens = set(_canonical_tokens(entry["name"]))
        if not entry_tokens:
            continue
        shared = candidate_tokens & entry_tokens
        if not shared:
            continue
        score = len(shared)
        if score > best_score:
            best_score = score
            best_symbol = entry["symbol"]

    if best_score >= 2:
        return best_symbol
    return ""


def find_symbols_from_text(text: str, catalog: Optional[List[dict]] = None) -> List[Tuple[str, str]]:
    print(f"Finding symbols from text: {text}, catalog: {len(catalog) if catalog else 'None'}")
    catalog = catalog or load_catalog()
    candidates = extract_title_candidates(text)
    if not candidates:
        candidates = [text]

    matches: List[Tuple[str, str]] = []
    for candidate in candidates:
        symbol = match_company_to_symbol(candidate, catalog)
        matches.append((candidate, symbol))
    return matches


# print("Stocks to Watch Today: PB Fintech, Bajaj Finance, CSB Bank, Ujjivan SFB, Marico, Titagarh Rail, BLS E-Services, Adani Enterprises in focus on 03 July- Moneycontrol.com","2093")