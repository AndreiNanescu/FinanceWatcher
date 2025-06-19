from sentence_transformers import SentenceTransformer
from typing import List, Union

class Embedder:
    def __init__(self, model_name: str = 'BAAI/bge-m3'):
        self.model = SentenceTransformer(model_name)

    def embed(self, texts: Union[str, List[str]]):
        if isinstance(texts, str):
            texts = [texts]

        text = [f"represents: {text}" for text in texts]
        embeddings = self.model.encode(text, normalize_embeddings=True)

        return embeddings[0] if len(embeddings) == 1 else embeddings
