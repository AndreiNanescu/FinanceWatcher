import atexit
import logging
import sys
from datetime import datetime

from tqdm import tqdm

from backend.config import LOGS_DIR

from .constants import DATE_FORMAT

LOG_FILE_PATH = None


class TqdmLoggingHandler(logging.StreamHandler):
    def __init__(self, stream=sys.stdout):
        super().__init__(stream)

    def emit(self, record):
        try:
            msg = self.format(record)
            tqdm.write(msg)
            self.flush()
        except Exception:
            self.handleError(record)


def _cleanup():
    for handler in logger.handlers:
        try:
            handler.flush()
            handler.close()
        except Exception:
            pass
    logging.shutdown()


def setup_logger(name: str = "shared_run_logger", level=logging.DEBUG):
    global LOG_FILE_PATH

    logger = logging.getLogger(name)
    logger.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(filename)s:%(lineno)d | %(funcName)s() | %(message)s",
        datefmt=DATE_FORMAT,
    )

    stream_handler = TqdmLoggingHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    logs_dir = LOGS_DIR
    logs_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    LOG_FILE_PATH = logs_dir / f"log_{timestamp}.log"

    file_handler = logging.FileHandler(LOG_FILE_PATH, mode="a", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.propagate = False

    atexit.register(_cleanup)

    logger.log_file_path = LOG_FILE_PATH
    return logger


logger = setup_logger()
