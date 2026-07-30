"""Loguru-based logging setup, wired to intercept stdlib logging too."""

import logging
import sys
from pathlib import Path

from loguru import logger

from app.core.config import get_settings


class InterceptHandler(logging.Handler):
    """Routes stdlib `logging` records (uvicorn, sqlalchemy, ...) into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def configure_logging() -> None:
    """Configure loguru sinks and redirect stdlib logging into loguru.

    Safe to call multiple times (e.g. across test modules); it resets sinks
    before reconfiguring so duplicate handlers never accumulate.
    """
    settings = get_settings()

    logger.remove()

    console_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format=console_format,
        colorize=True,
        backtrace=True,
        diagnose=settings.app_env != "production",
    )

    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_dir / "app.log",
        level=settings.log_level,
        rotation="50 MB",
        retention="14 days",
        compression="zip",
        serialize=settings.log_json,
        backtrace=True,
        diagnose=False,
        enqueue=True,
    )

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for noisy_logger in ("uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(noisy_logger).handlers = [InterceptHandler()]
        logging.getLogger(noisy_logger).propagate = False
