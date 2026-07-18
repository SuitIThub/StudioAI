"""CLI entry: studio-ai-core"""

from __future__ import annotations

import logging
import sys

import uvicorn

from studio_ai_core.config import settings_from_config
from studio_ai_core.core_ports import CORE_PORT_MAX, CORE_PORT_MIN, pick_listen_port


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

    # Ghost LISTEN after hard kills: walk 7200–7299 like StudioPoseBridge (7100–7199).
    preferred = settings.port
    if preferred < CORE_PORT_MIN or preferred > CORE_PORT_MAX:
        logging.warning(
            "core.port=%s outside %s–%s (ghost-port range); using %s as start",
            preferred,
            CORE_PORT_MIN,
            CORE_PORT_MAX,
            CORE_PORT_MIN,
        )
        preferred = CORE_PORT_MIN

    port = pick_listen_port(settings.host, preferred)
    settings.port = port
    logging.info(
        "StudioAI Core LOCKED on http://%s:%s/  (range %s–%s; Plugin discovers once then locks)",
        settings.host if settings.host != "0.0.0.0" else "127.0.0.1",
        port,
        CORE_PORT_MIN,
        CORE_PORT_MAX,
    )
    uvicorn.run(
        "studio_ai_core.app:app",
        host=settings.host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
