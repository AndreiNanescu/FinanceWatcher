import ollama
import re

from datetime import datetime
from textwrap import dedent
from typing import List, Dict

from ..rag import ChromaMarketNews



class Llama3:
    def __init__(self, chroma: ChromaMarketNews):
        self.chroma = chroma
        self._url_pattern = re.compile(r'\n?URL: .+\n?')
        self._published_on_pattern = re.compile(r'Published on:.*(?:\n|$)', flags=re.IGNORECASE)
        self._description_pattern = re.compile(r'Description:\s*(.+?)(?:\n\s*\n|$)', re.DOTALL | re.IGNORECASE)

    def _clean_document(self, raw_doc: str) -> str:
        doc = self._url_pattern.sub('\n', raw_doc)
        doc = self._published_on_pattern.sub('', doc).strip()
        return doc

    def _extract_description(self, cleaned_doc: str) -> str:
        match = self._description_pattern.search(cleaned_doc)
        return match.group(1).strip() if match else "No description available."

    def _build_context(self, news_items: List[Dict]) -> str:
        if not news_items:
            return "No relevant news found."

        lines = []
        for item in news_items:
            raw_doc = item.get("document", "")
            meta = item.get("metadata", {})

            cleaned_doc = self._clean_document(raw_doc)
            description = self._extract_description(cleaned_doc)

            title = meta.get("title", "Untitled").strip()
            source = meta.get("source", "Unknown source").strip()
            entity = meta.get("entity", "Unknown entity").strip()
            symbol = meta.get("symbol", "").strip()
            entity_str = f"{entity} ({symbol})" if symbol else entity
            sentiment = meta.get("sentiment_label", "Unknown sentiment").strip()
            industry = meta.get("industry", "Unknown industry").strip()

            published_at = meta.get("published_at", "Unknown date")
            try:
                date = datetime.fromisoformat(published_at.replace("Z", "")).date()
            except Exception:
                date = published_at

            lines.append(
                f"- ({date}) Title: {title}\n"
                f"  Source: {source}\n"
                f"  Description: {description}\n"
                f"  Mentioned Entity: {entity_str}\n"
                f"  Sentiment: {sentiment}\n"
                f"  Industry: {industry}"
            )

        return "\n\n".join(lines)

    @staticmethod
    def _build_prompt(context: str, question: str) -> List[Dict]:
        system_message = dedent(f"""
            You are a knowledgeable and confident financial analyst AI. Using ONLY the news excerpts provided in the context below, answer the question precisely and objectively.

            Context:
            {context}

            Instructions:
            - Do NOT mention “news excerpts,” “provided information,” or any reference to sources.
            - Present a clear, decisive, and concise analysis with no hedging or filler phrases.
            - Group related risks, trends, and opportunities logically without repeating points.
            - Avoid mentioning specific dates unless critical to understanding.
            - Use natural, professional, and assertive language.
            - Conclude with a focused summary that highlights key risks and potential outcomes or next steps.
            - If the question is unrelated to finance or markets, politely state that you are specialized in financial analysis and cannot provide an answer.
        """)

        return [
            {"role": "system", "content": system_message},
            {"role": "user", "content": question}
        ]

    def ask(self, question: str) -> str:
        news = self.chroma.query(query_text=question, top_n_rerank=10)
        context = self._build_context(news)
        messages = self._build_prompt(context, question)
        response = ollama.chat(model='llama3', messages=messages)
        return response.message.content

