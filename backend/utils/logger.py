import logging
from pathlib import Path
from datetime import datetime
import sys
from tqdm import tqdm

LOG_FILE_PATH = None


class TqdmLoggingHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            tqdm.write(msg)
            self.flush()
        except Exception:
            self.handleError(record)


def setup_logger(name: str = __name__, level=logging.DEBUG):
    global LOG_FILE_PATH

    # Auto-detect if main script is 'data_pipeline.py'
    main_script = Path(sys.argv[0]).name
    save_log = main_script == "data_pipeline.py"

    save = False
    if LOG_FILE_PATH is None and save_log:
        root_path = Path(__file__).resolve().parent.parent
        logs_dir = root_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        LOG_FILE_PATH = logs_dir / f"log_{timestamp}.log"
        save = True

    formatter = logging.Formatter(
        fmt='%(asctime)s | %(levelname)-8s | %(filename)s:%(lineno)d | %(funcName)s() | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    logger = logging.getLogger("shared_run_logger")
    logger.setLevel(level)

    if logger.hasHandlers():
        return logger

    # Stream handler that doesn't mess up tqdm
    stream_handler = TqdmLoggingHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    if save:
        file_handler = logging.FileHandler(LOG_FILE_PATH, mode='a')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logger.propagate = False

    return logger
