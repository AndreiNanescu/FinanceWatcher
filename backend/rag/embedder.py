from typing import cast

from sentence_transformers import SentenceTransformer

from backend.utils import logger

from .device import safe_device


class Embedder:
    def __init__(self, model_name: str = "BAAI/bge-m3", verbose: bool = False):
        self.model = SentenceTransformer(model_name, device=safe_device())
        self.verbose = verbose

        if self.verbose:
            logger.info("BAAI/bge-m3 embedder loaded and ready")

    def __call__(self, input: list[str]) -> list[list[float]]:
        text_with_prompt = [f"represents: {text}" for text in input]
        embeddings = self.model.encode(text_with_prompt, normalize_embeddings=True)
        return cast(list[list[float]], embeddings.tolist())

    def embed(self, texts: str | list[str]):
        if isinstance(texts, str):
            texts = [texts]

        return self.__call__(texts)

    def name(self):
        return "BAAI/bge-m3"
