import torch
from transformers import AutoTokenizer, AutoModelForTokenClassification
from typing import List, Tuple

from backend.utils import logger, normalize_name

class EntityAndTickerExtractor:
    def __init__(self, ner_model: str = "dslim/bert-base-NER-uncased", ticker_model: str = "Jean-Baptiste/roberta-ticker",
                 device: str = None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        self.ner_tokenizer = AutoTokenizer.from_pretrained(ner_model)
        self.ner_model = AutoModelForTokenClassification.from_pretrained(ner_model).to(self.device)
        self.ner_model.eval()
        self.ner_id2label = self.ner_model.config.id2label
        logger.info("NER model loaded and ready.")

        self.ticker_tokenizer = AutoTokenizer.from_pretrained(ticker_model)
        self.ticker_model = AutoModelForTokenClassification.from_pretrained(ticker_model).to(self.device)
        self.ticker_model.eval()
        self.ticker_id2label = self.ticker_model.config.id2label
        logger.info("Ticker model loaded and ready.")

    def extract_company_names(self, text: str) -> List[str]:
        inputs = self.ner_tokenizer(text, return_tensors="pt", truncation=True)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.ner_model(**inputs)
            predictions = outputs.logits.argmax(dim=-1)

        tokens = self.ner_tokenizer.convert_ids_to_tokens(inputs["input_ids"][0])
        labels = [self.ner_id2label[p.item()] for p in predictions[0]]

        entities = []
        current = []
        for token, label in zip(tokens, labels):
            if label.startswith("B-ORG") or label.startswith("I-ORG"):
                current.append(token)
            elif current:
                entities.append(self._clean_tokens(current))
                current = []
        if current:
            entities.append(self._clean_tokens(current))

        normalized_entities = [normalize_name(e) for e in entities]
        return normalized_entities

    def extract_tickers(self, text: str) -> List[str]:
        inputs = self.ticker_tokenizer(text, return_tensors="pt", truncation=True)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.ticker_model(**inputs)
            predictions = outputs.logits.argmax(dim=-1)

        tokens = self.ticker_tokenizer.convert_ids_to_tokens(inputs["input_ids"][0])
        labels = [self.ticker_id2label[p.item()] for p in predictions[0]]

        tickers = []
        current = []
        for token, label in zip(tokens, labels):
            if label.startswith("B-"):
                if current:
                    tickers.append("".join(current).replace("Ġ", ""))
                current = [token]
            elif label.startswith("I-"):
                if current:
                    current.append(token)
                else:
                    current = [token]
            else:
                if current:
                    tickers.append("".join(current).replace("Ġ", ""))
                    current = []
        if current:
            tickers.append("".join(current).replace("Ġ", ""))

        return list(set(t.upper() for t in tickers))

    def extract_all(self, text: str) -> Tuple[List[str], List[str]]:
        return self.extract_company_names(text), self.extract_tickers(text)

    @staticmethod
    def _clean_tokens(tokens: List[str]) -> str:
        clean = " ".join(t.lstrip("Ġ") for t in tokens)
        return clean.replace(" ##", "").replace(" ##", "").strip()
