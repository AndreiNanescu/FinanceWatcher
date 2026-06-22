from sentence_transformers import SentenceTransformer
from typing import List, Union
import torch

from backend.utils import logger


def _safe_device() -> str:
    """Return 'cuda' only if this GPU's arch is in PyTorch's compiled arch list."""
    if not torch.cuda.is_available():
        return "cpu"
    try:
        major, minor = torch.cuda.get_device_capability(0)
        if f"sm_{major}{minor}" in torch.cuda.get_arch_list():
            return "cuda"
    except Exception:
        pass
    return "cpu"


class Embedder:
    def __init__(self, model_name: str = 'BAAI/bge-m3', verbose: bool = False):
        self.model = SentenceTransformer(model_name, device=_safe_device())
        self.verbose= verbose

        if self.verbose:
            logger.info("BAAI/bge-m3 embedder loaded and ready")

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
