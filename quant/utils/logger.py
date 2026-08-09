"""??????????? + ??????????"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_configured = False
_file_handler: RotatingFileHandler | None = None
_loggers: dict[str, logging.Logger] = {}
LOG_DIR = Path("data/logs")


def _make_formatter() -> logging.Formatter:
    return logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def setup_logger(name: str = "quant", level: int = logging.INFO, log_dir: str | Path | None = None) -> logging.Logger:
    """?? logger???? stdout ?????????? 5MB ?? 5 ???"""
    global _configured
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(_make_formatter())
    logger.addHandler(console)

    if not _configured and log_dir is not None:
        setup_file_logging(log_dir)
    if _file_handler is not None:
        logger.addHandler(_file_handler)
    logger.propagate = False
    _loggers[name] = logger
    return logger


def setup_file_logging(log_dir: str | Path) -> None:
    """??? logger ?????? handler?Web ?????????"""
    global _configured, _file_handler
    if _configured:
        return
    _configured = True
    path = Path(log_dir)
    path.mkdir(parents=True, exist_ok=True)
    _file_handler = RotatingFileHandler(
        path / "quantx.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    _file_handler.setFormatter(_make_formatter())
    for logger in _loggers.values():
        if _file_handler not in logger.handlers:
            logger.addHandler(_file_handler)
