# FinanceWatcher ![logo](./frontend/public/logo.png)

**Track the sentiment. Measure the impact. Understand the markets.**

FinanceWatcher is an AI-powered utility that analyzes financial news and social media for sentiment and short-term market impact. By combining LLM-powered RAG (Retrieval-Augmented Generation), sentiment scoring, and price trend tracking, it helps users gain actionable insights into how the market reacts to news.

---

## Features

-  **News Ingestion & Embedding**  
  Ingest financial news, generate vector embeddings using *BAAI/bge-m3*, and store metadata-rich entries in a ChromaDB vector store.

- **Sentiment Analysis**  
  Extract sentiment scoring provided by the MarketAux API.

- **Impact Measurement**  
  Quantify how a stock's price changed due to the news article.

-  **Model Context Protocol (MCP) Tools**  
  Structured tools to let the LLM retrieve sentiment trends, calculate impact, price trends and current price.

-  **RAG-Powered Q&A**  
  Use embeddings + metadata for context-aware LLM interactions — explore recent news with a smart query system that is semnatically aware of the company and other keywords, **eg: 'BLK earnings', "Microsoft AI news" etc.**

---

##  Tech Stack

| Layer | Tools Used                          |
|------|-------------------------------------|
| Backend | Flask, Python                       |
| Embedding | BAAI/bge-m3                         |
| Reranker | BGEReranker |
| LLM  | LLama3                              |
| Vector DB | ChromaDB                            |
| MCP Tools | Anthropic Python SDK (MCP protocol) |
| Data | MarketAux API                       |
| Frontend | React                               |

---

## ✅ TODO

- [x] Set up news ingestion pipeline
- [x] Integrate Huggingface embeddings
- [x] Implement sentiment scoring
- [ ] Calculate price-based impact scores
- [x] Create core MCP tools
- [x] Add basic RAG query flow
- [x] Build frontend dashboard

---

## Author

FinanceWatcher by [Andrei Nanescu]


