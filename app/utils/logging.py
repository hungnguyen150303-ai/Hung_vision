import logging, os
from logging.handlers import RotatingFileHandler
from pathlib import Path

def configure_logging():
    level = os.environ.get("LOG_LEVEL", "INFO").upper()

    # Root logger
    logger = logging.getLogger()
    logger.setLevel(level)

    # Tránh add handler trùng
    if logger.handlers:
        return logging.getLogger("vision")

    # Console
    sh = logging.StreamHandler()
    sh.setLevel(level)
    sh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))

    # File (xoay vòng)
    log_dir = Path("/app/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(log_dir / "service.log", maxBytes=5_000_000, backupCount=3)
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))

    logger.addHandler(sh)
    logger.addHandler(fh)

    return logging.getLogger("vision")
