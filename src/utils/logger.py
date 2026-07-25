import sys

from loguru import logger

from src.config import settings

logger.remove()
logger.add(
    sys.stderr,
    level=settings.log_level,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}:{function}:{line}</cyan> | <level>{message}</level>",
    colorize=True,
)
logger.add(
    "logs/bot_{time:YYYY-MM-DD}.log",
    level="DEBUG",
    rotation="10 MB",
    retention="7 days",
    compression="gz",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
)

__all__ = ["logger"]
