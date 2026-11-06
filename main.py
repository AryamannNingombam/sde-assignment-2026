"""Entrypoint for the outcome-first agent loop controller."""

import logging
import sys

from config import SIM_BASE_URL, TICK_MINUTES, DB_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("controller")


def main() -> int:
    log.info("controller starting")
    log.info(
        "sim_base_url=%s tick_minutes=%s db_path=%s",
        SIM_BASE_URL,
        TICK_MINUTES,
        DB_PATH,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())