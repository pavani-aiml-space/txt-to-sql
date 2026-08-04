"""One place to configure how the agent's logger.info/.warning calls get
displayed and stored.

Purpose: give every entrypoint the same, one-line-to-call logging setup.
Needed so query activity is visible and kept, not just printed once and
lost. Works via logging.basicConfig, writing to both stderr and
data/nlq.log. nlq/text_to_sql.py's logger stays a NullHandler by default
(library convention); entrypoints opt in by calling this.
"""

import logging
import sys
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "nlq.log"


def configure_logging(level: int = logging.INFO, log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=level,
        format="[nlq] %(asctime)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stderr),
            logging.FileHandler(log_path),
        ],
    )
