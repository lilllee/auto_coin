import sys
from pathlib import Path

from loguru import logger


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    logger.remove()
    logger.add(sys.stderr, level=level, enqueue=True)
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_dir / "auto_coin_{time:YYYY-MM-DD}.log",
            level=level,
            rotation="00:00",
            retention="14 days",
            enqueue=True,
        )
