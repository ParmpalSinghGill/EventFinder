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

    def test_write_failure_outputs_creates_review_and_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)
            write_failure_outputs(out_dir, datetime(2026, 7, 8), "network issue")

            review_path = out_dir / "MC_review_20260708.txt"
            missing_path = out_dir / "MC_missing_20260708.txt"
            self.assertTrue(review_path.exists())
            self.assertTrue(missing_path.exists())
            self.assertIn("network issue", review_path.read_text(encoding="utf-8"))
            self.assertEqual(missing_path.read_text(encoding="utf-8"), "")


if __name__ == "__main__":
    unittest.main()
