import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class EvaluationDatasetTests(unittest.TestCase):
    def test_checked_in_questions_have_balanced_categories_and_valid_labels(self):
        questions = [
            json.loads(line)
            for line in (ROOT / "eval" / "tcs_questions.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(questions), 30)
        self.assertEqual(
            {category: sum(row["category"] == category for row in questions)
             for category in ("text", "table", "chart")},
            {"text": 10, "table": 10, "chart": 10},
        )
        for item in questions:
            with self.subTest(question=item["id"]):
                self.assertTrue(item["question"])
                self.assertTrue(item["pages"])
                self.assertTrue(item["evidence"])
                re.compile(item["answer_regex"])

    def test_public_sample_report_is_present_in_repository(self):
        self.assertTrue((ROOT / "data" / "pdfs" / "tcs-annual-report-fy2025-26.pdf").is_file())


if __name__ == "__main__":
    unittest.main()
