import torch

from typing import List, Tuple
from transformers import AutoTokenizer, AutoModelForSequenceClassification

from utils import setup_logger

logger = setup_logger(__name__)

class BGEReranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-base", device: str = None):
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device)
        self.model.eval()

        logger.info('Initialized reranker')

    def rerank(self, query: str, passages: List[str], top_k: int = 5) -> List[Tuple[str, float]]:
        pairs = [(query, passage) for passage in passages]
        inputs = self.tokenizer(pairs, padding=True, truncation=True, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            logits = self.model(**inputs).logits.squeeze(-1)

        scores = logits.cpu().tolist()
        passage_scores = list(zip(passages, scores))
        passage_scores.sort(key=lambda x: x[1], reverse=True)

        return passage_scores[:top_k]
