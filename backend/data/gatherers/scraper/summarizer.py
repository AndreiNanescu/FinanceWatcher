import re
import torch

from keybert import KeyBERT
from sentence_transformers import SentenceTransformer
from typing import Dict, List

from backend.models import Llama3


class ArticleSummarizer:
    def __init__(
        self,
        use_better_keybert_model: bool = True,
        max_input_tokens: int = 1024,
        device: str = None,
    ):
        self.llama3 = Llama3()
        self.max_input_tokens = max_input_tokens

        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        if use_better_keybert_model:
            sbert_model = SentenceTransformer("distilbert-base-nli-mean-tokens")
            self.keyword_extractor = KeyBERT(model=sbert_model)
        else:
            self.keyword_extractor = KeyBERT()


    def summarize(self, text: str) -> Dict[str, str]:
        if not text.strip():
            return {"summary": "", "keywords": []}

        cleaned_text = self._clean_text(text)

        try:
            initial_summary = self.llama3.summarize(cleaned_text)
            initial_summary = self._postprocess_summary(initial_summary)

            summary_compressed = self.llama3.resummarize(initial_summary)

            keywords = self._extract_keywords(cleaned_text)

            return {
                "summary": summary_compressed,
                "keywords": keywords
            }
        except Exception as e:
            raise RuntimeError(f"Summarization failed: {str(e)}")

    @staticmethod
    def _clean_text(text: str) -> str:
        blocklist = ["subscribe", "sign up", "download", "alert"]
        lines = text.splitlines()
        useful_lines = []
        for line in lines:
            stripped = line.strip()
            if len(stripped) <= 40:
                continue

            if any(re.search(rf"\b{re.escape(phrase)}\b", stripped.lower()) for phrase in blocklist):
                continue
            useful_lines.append(stripped)
        return "\n".join(useful_lines)

    @staticmethod
    def _postprocess_summary(summary: str) -> str:
        summary = re.sub(r"[*\-•]+", "", summary)
        lines = summary.splitlines()
        cleaned_lines = [line.strip() for line in lines if line.strip()]
        return " ".join(cleaned_lines)

    def _extract_keywords(self, text: str) -> List[str]:
        keywords = self.keyword_extractor.extract_keywords(
            text,
            keyphrase_ngram_range=(1, 2),
            stop_words="english",
            top_n=15,
            diversity=0.7
        )

        seen = set()
        clean_keywords = []

        for phrase, _ in keywords:
            cleaned = re.sub(r'[^a-zA-Z0-9 ]', '', phrase.lower()).strip()
            if cleaned and self._is_valid_keyword(cleaned) and cleaned not in seen:
                seen.add(cleaned)
                clean_keywords.append(phrase)
            if len(clean_keywords) >= 7:
                break

        return clean_keywords

    @staticmethod
    def _is_valid_keyword(kw: str) -> bool:
        bad_patterns = ["2020", "shows april", "virus", "buying stocks", "edge"]
        return not any(bp in kw for bp in bad_patterns)