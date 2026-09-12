"""日志与节奏工具。"""
import logging
import random
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """控制台 + 文件（logs/bili.log，2MB 滚动 3 份）双输出。"""
    root = logging.getLogger("bili")
    if root.handlers:
        return root
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_h = RotatingFileHandler(
        LOG_DIR / "bili.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_h.setFormatter(fmt)
    root.addHandler(file_h)
    return root


def sleep_random(a: float, b: float) -> None:
    """随机间隔，避免固定节奏（8~25 秒量级）。"""
    t = random.uniform(a, b)
    logging.getLogger("bili").debug("sleep %.1fs", t)
    time.sleep(t)
