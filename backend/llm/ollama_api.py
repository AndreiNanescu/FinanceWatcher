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
            entity = meta.get("entity", "Unknown entity").strip()
            symbol = meta.get("symbol", "").strip()
            entity_str = f"{entity} ({symbol})" if symbol else entity
            sentiment = meta.get("sentiment_label", "Unknown sentiment").strip()
            industry = meta.get("industry", "Unknown industry").strip()
            published_at = meta.get("published_at", "Unknown date")
            url = meta.get("url", "Unknown url")

            try:
                date = datetime.fromisoformat(published_at.replace("Z", "")).date()
            except Exception:
                date = published_at

            lines.append(
                f"- ({date}) Title: {title}\n"
                f"  Description: {description}\n"
                f"  Mentioned Entity: {entity_str}\n"
                f"  Sentiment: {sentiment}\n"
                f"  Industry: {industry}\n"
                f"  Url: {url}"
            )

        return "\n\n".join(lines)

    @staticmethod
    def _build_prompt(context: str, question: str) -> List[Dict]:
        system_message = dedent(f"""
            You are a knowledgeable and concise financial analyst AI. Based ONLY on the news excerpts in the context below, respond to the user's question accurately and professionally.

            Context:
            {context}

            Instructions:
            - Organize the answer using **bold section headers** (e.g., **Company Overview:**).
            - Each section must contain 1 or more full paragraphs.
            - For risks and opportunities, use a **numbered list**. Each item should begin plainly like "1. Risk description".
              - Do NOT use bold, italics, or subheaders inside list items.
            - Do NOT place section headers on the same line as list items or paragraph content.
            - Do NOT use any markdown other than:
              - Bold section headers (`**Header:**`)
              - Inline links (`*url: FULL_LINK*`)

            Citations:
            - Cite sources using *url: FULL_LINK* format.
            - Place citations inline at the **end of the sentence or paragraph** where the information is used.
            - Do NOT include a "References" section or list all links at the end.
            - Never invent, reword, or omit any URLs from the provided context.

            Output Format Summary:
            - Section headers: **Header:**
            - Paragraphs under each header
            - Numbered lists for risks/opportunities
            - Inline citations using *url: LINK*
            - No other markdown or formatting
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

