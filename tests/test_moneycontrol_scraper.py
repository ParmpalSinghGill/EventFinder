import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from scrape_moneycontrol_stocks import build_manual_review_text, find_article_link_for_date, write_failure_outputs


class MoneycontrolScraperTests(unittest.TestCase):
    def test_prefers_real_article_links_and_matches_day_without_zero_padding(self) -> None:
        html = """
        <html><body>
          <a href="https://www.moneycontrol.com/news/">News</a>
          <a href="https://www.moneycontrol.com/news/business/markets/stocks-to-watch-today-foo-in-focus-on-8-july-13900000.html">
            Stocks to Watch Today
          </a>
        </body></html>
        """
        target_dt = datetime(2026, 7, 8)

        link = find_article_link_for_date(html, target_dt)

        self.assertEqual(
            link,
            "https://www.moneycontrol.com/news/business/markets/stocks-to-watch-today-foo-in-focus-on-8-july-13900000.html",
        )

    def test_manual_review_text_includes_title_link_and_missing_names(self) -> None:
        review_text = build_manual_review_text(
            "Stocks to Watch Today: Orchid Pharma",
            "https://www.moneycontrol.com/news/example.html",
            ["ORCHPHARMA"],
            ["Knack Packaging", "IdeaForge"],
        )

        self.assertIn("Stocks to Watch Today: Orchid Pharma", review_text)
        self.assertIn("Read More:", review_text)
        self.assertIn("https://www.moneycontrol.com/news/example.html", review_text)
        self.assertIn("No ticker found:", review_text)
        self.assertIn("Knack Packaging", review_text)

    def test_ticker_mapping_aliases_and_exact_symbols(self) -> None:
        from ticker_mapping import load_catalog, match_company_to_symbol
        catalog = load_catalog()

        self.assertEqual(match_company_to_symbol("TCS", catalog), "TCS")
        self.assertEqual(match_company_to_symbol("GE Shipping", catalog), "GESHIP")
        self.assertEqual(match_company_to_symbol("SBI", catalog), "SBIN")
        self.assertEqual(match_company_to_symbol("EMS", catalog), "EMS")
        self.assertEqual(match_company_to_symbol("Dr Reddys Labs", catalog), "DRREDDY")
        self.assertEqual(match_company_to_symbol("Afcons Infra", catalog), "AFCONS")
        self.assertEqual(match_company_to_symbol("Hindustan Copper", catalog), "HINDCOPPER")
        self.assertEqual(match_company_to_symbol("Piramal Finance", catalog), "PIRAMALFIN")


if __name__ == "__main__":
    unittest.main()
