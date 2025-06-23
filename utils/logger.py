import logging
from pathlib import Path
from datetime import datetime

LOG_FILE_PATH = None


def setup_logger(name: str = __name__, level=logging.DEBUG):
    global LOG_FILE_PATH

    if LOG_FILE_PATH is None:
        root_path = Path(__file__).resolve().parent.parent
        logs_dir = root_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        LOG_FILE_PATH = logs_dir / f"log_{timestamp}.log"

    formatter = logging.Formatter(
        fmt='%(asctime)s | %(levelname)-8s | %(filename)s:%(lineno)d | %(funcName)s() | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    logger = logging.getLogger("shared_run_logger")
    logger.setLevel(level)

    if logger.hasHandlers():
        return logger

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(LOG_FILE_PATH, mode='a')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.propagate = False

    return logger
