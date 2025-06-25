import queue
import threading
import time

from backend.utils import Article, setup_logger
from backend.rag.chroma import ChromaMarketNews

logger = setup_logger(__name__)


class BackgroundIndexer:
    def __init__(self, chroma: ChromaMarketNews):
        self.chroma = chroma
        self.queue = queue.Queue()
        self._stop_event = threading.Event()

        self.worker = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker.start()

    def index_article(self, article: Article):
        self.queue.put(article)

    def _worker_loop(self):
        while not self._stop_event.is_set():
            try:
                article = self.queue.get(timeout=1)
                self.chroma_upsert_article(article)
                self.queue.task_done()
            except queue.Empty:
                continue
            except Exception as exception:
                logger.warning(f' Indexer error: {exception}')
                time.sleep(2)

    def stop(self):
        self._stop_event.set()
        self.worker.join()
