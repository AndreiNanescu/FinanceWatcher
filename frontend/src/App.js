import React, { useState, useEffect, useRef } from "react";
import axios from "axios";

function TypingIndicator() {
  return (
    <div className="flex items-center h-5 p-3 rounded-xl bg-modern-dark-tertiary max-w-[85%] self-start">
      <div
        className="w-2 h-2 bg-modern-dark-text-secondary rounded-full mx-0.5 animate-bounce"
        style={{ animationDelay: "0s" }}
      ></div>
      <div
        className="w-2 h-2 bg-modern-dark-text-secondary rounded-full mx-0.5 animate-bounce"
        style={{ animationDelay: "0.2s" }}
      ></div>
      <div
        className="w-2 h-2 bg-modern-dark-text-secondary rounded-full mx-0.5 animate-bounce"
        style={{ animationDelay: "0.4s" }}
      ></div>
    </div>
  );
}

function TypingMessage({ text, onComplete }) {
  const [displayedText, setDisplayedText] = useState("");
  const typingInterval = useRef(null);

  useEffect(() => {
    if (!text) return;

    setDisplayedText("");
    let currentIndex = 0;

    typingInterval.current = setInterval(() => {
      if (currentIndex < text.length) {
        setDisplayedText((prev) => prev + text[currentIndex]);
        currentIndex++;
      } else {
        clearInterval(typingInterval.current);
        if (onComplete) onComplete();
      }
    }, 20);

    return () => {
      clearInterval(typingInterval.current);
    };
  }, [text, onComplete]);

  return (
    // Render typing text without box, same style as bot messages
    <div className="max-w-[85%] self-start text-modern-dark-text-primary whitespace-pre-wrap">
      {displayedText}
    </div>
  );
}

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [isWaiting, setIsWaiting] = useState(false);
  const chatContainerRef = useRef(null);

  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [messages, isTyping, isWaiting]);

  const sendMessage = async () => {
    if (!input.trim() || isTyping) return;

    const userMessage = {
      role: "user",
      content: input,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsWaiting(true);

    try {
      const res = await axios.post("http://localhost:5000/api/chat", {
        message: input,
      });

      const botResponse = res.data.response || "I couldn't generate a response";
      setIsWaiting(false);
      setIsTyping(true);

      setMessages((prev) => [
        ...prev,
        {
          role: "bot",
          content: botResponse,
          timestamp: new Date().toISOString(),
        },
      ]);
    } catch (error) {
      setIsWaiting(false);
      setMessages((prev) => [
        ...prev,
        {
          role: "bot",
          content: "Error: Could not get response",
          timestamp: new Date().toISOString(),
        },
      ]);
    }
  };

  const handleTypingComplete = () => {
    setIsTyping(false);
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="dark flex flex-col h-screen bg-modern-dark-primary text-modern-dark-text-primary font-sans">
      {/* Header */}
      <header className="flex justify-between items-center p-4 bg-modern-dark-header-input border-b border-modern-dark-border flex-shrink-0">
        <h1 className="text-xl m-0 font-medium">Finance Watcher</h1>
        <button
          onClick={() => setMessages([])}
          disabled={isTyping || isWaiting}
          className="bg-modern-dark-secondary hover:bg-modern-dark-tertiary text-modern-dark-text-primary border border-modern-dark-border px-3 py-1 rounded-lg cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          Clear
        </button>
      </header>

      {/* Chat area */}
      <div
        className="flex-1 p-6 overflow-y-auto flex flex-col gap-4 bg-modern-dark-secondary"
        ref={chatContainerRef}
      >
        {messages.map((msg, i) => {
          if (msg.role === "bot" && i === messages.length - 1 && isTyping) {
            return (
              <TypingMessage key={i} text={msg.content} onComplete={handleTypingComplete} />
            );
          }
          return (
            <div
              key={i}
              className={`max-w-[85%] ${
                msg.role === "user"
                  ? "p-4 rounded-xl bg-modern-dark-tertiary text-modern-dark-text-primary self-end rounded-br-none"
                  : "self-start text-modern-dark-text-primary whitespace-pre-wrap"
              }`}
              style={msg.role === "bot" ? { padding: 0, margin: 0 } : {}}
            >
              {msg.content}
              <div
                className={`text-xs mt-2 ${
                  msg.role === "user"
                    ? "text-indigo-100 text-right"
                    : "text-modern-dark-text-secondary text-left"
                }`}
              >
                {new Date(msg.timestamp).toLocaleTimeString()}
              </div>
            </div>
          );
        })}
        {isWaiting && <TypingIndicator />}
      </div>

      {/* Input area without outer box */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          sendMessage();
        }}
        className="p-4"
      >
        <div className="relative w-[95%] max-w-xl mx-auto">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type your message..."
            disabled={isTyping || isWaiting}
            rows={1}
            className="w-full p-3 pr-14 rounded-xl border border-modern-dark-border bg-modern-dark-secondary text-modern-dark-text-primary resize-none min-h-[40px] max-h-[120px] focus:outline-none focus:ring-2 focus:ring-modern-dark-accent focus:border-transparent disabled:opacity-50 transition-all"
          />
          <button
            type="submit"
            disabled={isTyping || isWaiting || !input.trim()}
            className="absolute right-3 top-1/2 -translate-y-1/2 h-9 w-9 rounded-full bg-modern-dark-accent text-white flex items-center justify-center disabled:bg-modern-dark-tertiary disabled:cursor-not-allowed hover:bg-modern-dark-accent-hover transition-colors"
          >
            {isWaiting || isTyping ? (
              <svg
                className="w-5 h-5 animate-spin"
                fill="none"
                viewBox="0 0 24 24"
                xmlns="http://www.w3.org/2000/svg"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                ></circle>
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                ></path>
              </svg>
            ) : (
              <svg
                className="w-5 h-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
                />
              </svg>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}

export default App;
