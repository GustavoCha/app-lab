"""Local entrypoint for the Vercel + Supabase alert cycle."""

from __future__ import annotations

import logging
import sys

from config.config import load_config
from services.alert_engine import run_alert_cycle


def configure_logging() -> None:
    """Configure console logging."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def main() -> int:
    """Run one alert cycle locally."""

    configure_logging()

    try:
        config = load_config()
    except ValueError as exc:
        logging.getLogger(__name__).error("%s", exc)
        return 1

    stats = run_alert_cycle(config)
    logging.getLogger(__name__).info("Alert cycle stats: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
