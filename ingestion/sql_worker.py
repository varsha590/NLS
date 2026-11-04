"""Isolated SQLGlot parser process used to enforce upload parse timeouts."""

from __future__ import annotations

import json
import sys

from ingestion.datasets import UploadError, _parse_sql_content


def main() -> int:
    request = json.load(sys.stdin)
    try:
        schema, value_documents, warnings = _parse_sql_content(
            request["sql_text"],
            request["dialect"],
            request["low_cardinality_max"],
        )
    except (UploadError, KeyError, TypeError, ValueError):
        return 2
    json.dump(
        {
            "schema": schema.to_dict(),
            "value_documents": value_documents,
            "warnings": warnings,
        },
        sys.stdout,
        ensure_ascii=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())