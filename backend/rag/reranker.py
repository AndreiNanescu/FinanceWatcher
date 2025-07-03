import torch

from typing import List, Tuple
from transformers import AutoTokenizer, AutoModelForSequenceClassification

from backend.utils import logger


class BGEReranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-base", device: str = None):
        self.model_name = model_name
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = None
        self.model = None
        logger.info("BGEReranker initialized but model/tokenizer not loaded yet")

    def _load_model(self):
        if self.tokenizer is None or self.model is None:
            logger.info(f"Loading model '{self.model_name}' on {self.device}...")
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
            self.model.to(self.device)
            self.model.eval()
            logger.info("BGEReranker loaded and ready")

    def rerank(self, query: str, passages: List[str], top_k: int = 5) -> List[Tuple[str, float]]:
        self._load_model()

        pairs = [(query, passage) for passage in passages]
        inputs = self.tokenizer(pairs, padding=True, truncation=True, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            logits = self.model(**inputs).logits.squeeze(-1)

        scores = logits.cpu().tolist()
        passage_scores = list(zip(passages, scores))
        passage_scores.sort(key=lambda x: x[1], reverse=True)

        return passage_scores[:top_k]
