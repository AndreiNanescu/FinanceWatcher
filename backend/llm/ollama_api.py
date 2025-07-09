import ollama
import re

from datetime import datetime
from textwrap import dedent
from typing import List, Dict

from backend.data import Querier


class Llama3:
    def __init__(self, querier: Querier = None):
        self.querier = querier

    def _clean_document(self, raw_doc: str) -> str:
        doc = re.sub(r'^Keywords present:.*(?:\n|$)', '', raw_doc, flags=re.MULTILINE)

        return doc.strip()

    def _build_context(self, news_items: List[Dict]) -> str:
        if not news_items:
            return "No relevant news found."

        lines = []
        for item in news_items:
            raw_doc = item.get("document", "")
            meta = item.get("metadata", {})

            cleaned_doc = self._clean_document(raw_doc)

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
                f"  Description: {cleaned_doc}\n"
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
        sub_queries = self.split_query(question)
        all_news = []

        for sub in sub_queries:
            news = self.querier.search(query_text=sub)
            all_news.extend(news)

        context = self._build_context(all_news)
        messages = self._build_prompt(context, question)
        response = ollama.chat(model='llama3', messages=messages)
        return response.message.content

    @staticmethod
    def summarize(article_text: str) -> str:
        text = article_text.strip()
        if not text:
            return ""

        system_message = dedent("""
            You are a precise and disciplined financial analyst AI.

            Your job is to generate clean and reliable **plain text** summaries of financial articles.

            Rules:
            - DO NOT invent or hallucinate any facts not in the article.
            - DO NOT include personal opinions or analysis.
            - DO NOT use any formatting: NO bullet points, NO bold (**), NO italics (*), NO markdown.
            - DO NOT leave extra line breaks between paragraphs.
            - DO NOT use headings like "Key events:" or "Investor impact:"
            - DO NOT include lists or numbered items.
            - Write only full, coherent paragraphs.

            Bad Example (Do not follow):
            - NVIDIA stock rose 2% today. *Strong earnings!*
            - **Great outlook for AI**
            - *Company is bullish on the future*

            Good Example:
            NVIDIA's stock rose after the company reported strong quarterly earnings, driven by continued growth in AI-related demand. Investors responded positively to the revenue beat, while analysts raised concerns about increasing competition in the space.

            Your summary must match the good example style exactly: plain, paragraph-based, fact-based writing.
        """)

        user_message = dedent(f"""
            Article:
            {text}

            Write the summary:
        """)

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message}
        ]

        response = ollama.chat(model='llama3', messages=messages)
        return response.message.content.strip()

    def resummarize(self, summary_text: str) -> str:
        text = summary_text.strip()
        if not text:
            return ""

        system_message = dedent("""
            You are a precise financial analyst AI focused on making summaries concise and clear.

            Your task is to compress the given summary while retaining all key facts.
            - Do NOT hallucinate or add information.
            - Do NOT use any formatting or markdown.
            - Avoid repetition and redundancy.
            - Write only in clean, plain paragraphs.
            - Make the summary as short as possible without losing essential meaning.
        """)

        user_message = dedent(f"""
            Summary:
            {text}

            Compressed Summary:
        """)

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message}
        ]

        response = ollama.chat(model='llama3', messages=messages)
        return response.message.content.strip()

    def split_query(self, question: str) -> List[str]:
        system_message = dedent("""
            You are an intelligent query simplifier for a financial assistant AI.

            Your task is to split a user’s compound financial query into multiple simple sub-queries.

            Instructions:
            - Return each sub-query as a short and clear sentence.
            - Sub-queries should focus on a single entity or topic.
            - Only include relevant parts: remove unnecessary filler or fluff.
            - Respond ONLY with a list of strings, no explanation or formatting.

            Example:

            Input:
            Give me the latest BLK earnings, aapl news, microsoft ai related news and amazon earnings.

            Output:
            ["BLK earnings", "AAPL news", "Microsoft AI news", "Amazon earnings"]
        """)

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": question}
        ]

        response = ollama.chat(model='llama3', messages=messages)

        try:
            return eval(response.message.content.strip())  # Safe-ish because we control the prompt
        except Exception:
            return [question.strip()]