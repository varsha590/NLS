"""Force-refresh the stored schema embedding index."""

import logging
import sys

from core.startup import init_app


def main() -> int:
    try:
        init_app(force=True)
    except Exception as error:
        logging.error("Schema reindexing failed", extra={"error_type": type(error).__name__})
        return 1
    logging.info("Schema re-indexing completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())