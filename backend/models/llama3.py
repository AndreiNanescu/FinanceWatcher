import ollama
from textwrap import dedent

from backend.data import Querier


class Llama3:
    def __init__(self, querier: Querier = None):
        self.querier = querier

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
    
    @staticmethod
    def resummarize(summary_text: str) -> str:
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
