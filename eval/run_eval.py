"""Evaluate execution accuracy against question and expected-SQL fixtures."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from core.startup import get_runtime, init_app
from validation.validator import validate_sql

LOGGER = logging.getLogger(__name__)


def _result_set(rows: list[dict[str, Any]]) -> set[tuple[tuple[str, str], ...]]:
    return {
        tuple(sorted((str(key), str(value)) for key, value in row.items()))
        for row in rows
    }


def main() -> int:
    """Run each evaluation case and report unordered result-set accuracy."""
    logging.basicConfig(level=logging.INFO)
    cases_path = Path(__file__).with_name("questions.json")
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    if not cases:
        LOGGER.error("No evaluation questions found in %s", cases_path)
        return 2
    init_app()
    runtime = get_runtime()
    pipeline = runtime["pipeline"]
    correct = 0
    for index, case in enumerate(cases, start=1):
        result = pipeline.run(case["question"])
        expected_sql = validate_sql(
            case["expected_sql"],
            metadata=runtime["metadata"],
            dialect=runtime["adapter"].get_sqlglot_dialect(),
            max_rows=runtime["settings"].max_rows,
            adapter=runtime["adapter"],
        )
        expected = runtime["adapter"].run_readonly_query(
            expected_sql, runtime["settings"].max_rows
        )
        passed = _result_set(result.rows) == _result_set(expected.rows)
        correct += int(passed)
        LOGGER.info("%s. %s: %s", index, "PASS" if passed else "FAIL", case["question"])
        if result.errors:
            LOGGER.warning("Pipeline errors for case %s: %s", index, result.errors)
    accuracy = correct / len(cases)
    LOGGER.info("Execution accuracy: %s/%s (%.1f%%)", correct, len(cases), accuracy * 100)
    return 0 if correct == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())