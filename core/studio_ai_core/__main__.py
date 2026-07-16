"""CLI entry: studio-ai-core"""

from __future__ import annotations

import logging
import sys

import uvicorn

from studio_ai_core.config import settings_from_config


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    try:
        settings = settings_from_config()
    except FileNotFoundError as exc:
        logging.error("%s", exc)
        sys.exit(1)
    uvicorn.run(
        "studio_ai_core.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
