from sentence_transformers import SentenceTransformer
from typing import List, Union


class Embedder:
    def __init__(self, model_name: str = 'BAAI/bge-m3'):
        self.model = SentenceTransformer(model_name)

    def __call__(self, input: List[str]) -> List[List[float]]:
        text_with_prompt = [f"represents: {text}" for text in input]
        embeddings = self.model.encode(text_with_prompt, normalize_embeddings=True)
        return embeddings.tolist()

    def embed(self, texts: Union[str, List[str]]):
        if isinstance(texts, str):
            texts = [texts]

        return self.__call__(texts)

    def name(self):
        return "BAAI/bge-m3"
