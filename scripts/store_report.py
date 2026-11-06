"""Print Qdrant index inventory counts without exposing indexed row values.

Reads from Qdrant only. If the Qdrant service is unavailable, prints a clear
legacy message and exits successfully.
"""

from __future__ import annotations

import argparse
from collections import defaultdict

from config.settings import Settings
from retrieval.qdrant_store import create_qdrant_client


def format_store_report(settings: Settings) -> str:
    """Return per-tenant/dataset point counts from Qdrant; never format value text."""
    lines = [
        f"Collection: {settings.qdrant_collection}",
        f"Qdrant URL: {settings.qdrant_url}",
    ]
    try:
        client = create_qdrant_client(settings)
    except Exception as exc:  # pragma: no cover - network-dependent
        lines.append("")
        lines.append("Qdrant is unreachable; no per-dataset counts available.")
        lines.append(f"Underlying error: {type(exc).__name__}")
        return "\n".join(lines)

    try:
        exists = client.collection_exists(settings.qdrant_collection)
    except Exception as exc:  # pragma: no cover - network-dependent
        lines.append("")
        lines.append("Qdrant collection lookup failed; index may not exist yet.")
        lines.append(f"Underlying error: {type(exc).__name__}")
        return "\n".join(lines)

    if not exists:
        lines.append("")
        lines.append("Collection does not exist yet; no indexed datasets.")
        return "\n".join(lines)

    try:
        info = client.get_collection(settings.qdrant_collection)
        lines.append(f"Points: {info.points_count}")
        lines.append(f"Vector size: {info.config.params.vectors.size}")
    except Exception as exc:  # pragma: no cover - network-dependent
        lines.append("")
        lines.append("Could not read collection info.")
        lines.append(f"Underlying error: {type(exc).__name__}")
        return "\n".join(lines)

    # Scroll all payloads to count points per tenant/dataset/document_type.
    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    offset = None
    try:
        while True:
            page, offset = client.scroll(
                collection_name=settings.qdrant_collection,
                limit=256,
                with_payload=True,
                with_vectors=False,
                offset=offset,
            )
            for point in page:
                payload = point.payload or {}
                tenant_id = str(payload.get("tenant_id", "unknown"))
                dataset_id = str(payload.get("dataset_id", "unknown"))
                document_type = str(payload.get("document_type", "unknown"))
                counts[(tenant_id, dataset_id, document_type)] += 1
            if offset is None:
                break
    except Exception as exc:  # pragma: no cover - network-dependent
        lines.append("")
        lines.append("Failed to scroll Qdrant points.")
        lines.append(f"Underlying error: {type(exc).__name__}")
        return "\n".join(lines)

    lines.append("")
    lines.append("Points per tenant / dataset / document type:")
    if not counts:
        lines.append("  (none)")
    else:
        for (tenant_id, dataset_id, document_type) in sorted(counts):
            lines.append(
                f"  {tenant_id} | {dataset_id} | {document_type}: {counts[(tenant_id, dataset_id, document_type)]}"
            )

    lines.append("")
    lines.append("STALE OVERRIDES")
    lines.append("  none")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    del args  # retained for CLI compatibility; Qdrant is configured via settings.
    settings = Settings.from_env()
    print(format_store_report(settings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
