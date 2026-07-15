"""CLI entry: studio-ai-worker"""

from __future__ import annotations

import logging

import uvicorn

from studio_ai_worker.config import settings_from_config


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    settings = settings_from_config()
    uvicorn.run(
        "studio_ai_worker.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
