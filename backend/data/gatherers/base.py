from abc import ABC, abstractmethod
from typing import List, Optional

class DataGatherer(ABC):
    def __init__(self, symbols: List[str], save_data: bool = False):
        if not symbols or not all(isinstance(s, str) for s in symbols):
            raise ValueError("Symbols must be a non-empty list of strings.")
        self.symbols = symbols
        self.save_data = save_data

    @abstractmethod
    def _save_raw_json(self, data: dict, base_dir: str = "./raw") -> str:
        ...

    @abstractmethod
    def get_data(self) -> Optional[dict]:
        ...