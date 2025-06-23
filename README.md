# 📈 FinanceWatcher

**Track the sentiment. Measure the impact. Understand the markets.**

FinanceWatcher is an AI-powered utility that analyzes financial news and social media for sentiment and short-term market impact. By combining LLM-powered RAG (Retrieval-Augmented Generation), sentiment scoring, and price trend tracking, it helps users gain actionable insights into how the market reacts to news.

---

## 🚀 Features

- 🔍 **News Ingestion & Embedding**  
  Ingest financial news and tweets, generate vector embeddings using Ollama models, and store metadata-rich entries in a ChromaDB vector store.

- 🧠 **Sentiment Analysis**  
  Run sentiment classification on financial news using LLM-backed or custom scoring.

- 📊 **Impact Measurement**  
  Quantify how a stock's price changed in the 1-hour window before and after each news item.

- 🧩 **Model Context Protocol (MCP) Tools**  
  Structured tools to let the LLM retrieve sentiment trends, calculate impact, and summarize insights.

- 🔎 **RAG-Powered Q&A**  
  Use embeddings + metadata for context-aware LLM interactions — explore recent market-moving news by company or sentiment.

---

## 🛠️ Tech Stack

| Layer        | Tools Used                          |
|--------------|-------------------------------------|
| Backend      | Flask, Python                       |
| LLM / Embedding | Huggingface (open-source models)    |
| Vector DB    | ChromaDB                            |
| MCP Tools    | Anthropic Python SDK (MCP protocol) |
| Data         | Financial news APIs / Twitter API   |
| Frontend     | Planned (React or simple Flask UI)  |


## 📈 Use Cases

- "Show me recent news with the strongest negative sentiment for $TSLA"
- "How did Apple’s stock move after the last major headline?"
- "What's the sentiment trend for NVIDIA over the past week?"

---

## ✅ TODO

- [x] Set up news ingestion pipeline
- [x] Integrate Huggingface embeddings
- [x] Implement sentiment scoring
- [ ] Calculate price-based impact scores
- [ ] Create core MCP tools
- [x] Add basic RAG query flow
- [ ] Build frontend dashboard (optional)

---

## 👤 Author

FinanceWatcher by [Andrei Nanescu]

---

*Initial README draft assisted by ChatGPT.*
