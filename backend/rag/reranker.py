from typing import Any

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from backend.utils import logger

from .device import safe_device


class BGEReranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-base", device: str | None = None, verbose: bool = False):
        self.model_name = model_name
        self.device = device or safe_device()
        self.tokenizer: Any = None
        self.model: Any = None
        self.verbose = verbose

        if self.verbose:
            logger.info("BGEReranker initialized but model/tokenizer not loaded yet")

    def _load_model(self):
        if self.tokenizer is None or self.model is None:
            if self.verbose:
                logger.info(f"Loading model '{self.model_name}' on {self.device}...")
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
            self.model.to(self.device)
            self.model.eval()

            if self.verbose:
                logger.info("BGEReranker loaded and ready")

    def rerank(self, query: str, passages: list[str], top_k: int = 5) -> list[tuple[str, float]]:
        self._load_model()

        if not passages:
            return []

        pairs = [(query, passage) for passage in passages]
        inputs = self.tokenizer(pairs, padding=True, truncation=True, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            logits = self.model(**inputs).logits.squeeze(-1)
            scores = torch.sigmoid(logits)

        if scores.dim() == 0:
            scores = scores.unsqueeze(0)

        passage_scores = [(p, s.item()) for p, s in zip(passages, scores, strict=False)]
        passage_scores.sort(key=lambda x: x[1], reverse=True)

        return passage_scores[:top_k]
