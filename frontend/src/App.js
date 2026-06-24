import React, { useState, useEffect, useRef } from "react";
import axios from "axios";


function Formatter({ text }) {
  const getWebsiteName = (url) => {
    try {
      const { hostname } = new URL(url);
      return hostname.replace(/^www\./, "");
    } catch {
      return url;
    }
  };

  const renderInline = (line, keyPrefix) => {
    const boldRegex = /\*\*(.+?)\*\*/g;
    const segments = [];
    let lastIndex = 0;
    let match;
    while ((match = boldRegex.exec(line)) !== null) {
      if (match.index > lastIndex) {
        segments.push({ bold: false, text: line.slice(lastIndex, match.index) });
      }
      segments.push({ bold: true, text: match[1] });
      lastIndex = match.index + match[0].length;
    }
    if (lastIndex < line.length) {
      segments.push({ bold: false, text: line.slice(lastIndex) });
    }

    const urlRegex = /(https?:\/\/[^\s)]+)/g;
    const nodes = [];
    segments.forEach((seg, si) => {
      let li = 0;
      let m;
      let ki = 0;
      const inner = [];
      while ((m = urlRegex.exec(seg.text)) !== null) {
        if (m.index > li) inner.push(seg.text.slice(li, m.index));
        const url = m[1].replace(/[.,]+$/, "");
        inner.push(
          <a
            key={`${keyPrefix}-${si}-${ki}`}
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-modern-dark-accent underline"
          >
            {getWebsiteName(url)}
          </a>
        );
        li = m.index + m[1].length;
        ki++;
      }
      if (li < seg.text.length) inner.push(seg.text.slice(li));

      if (seg.bold) {
        nodes.push(
          <strong key={`${keyPrefix}-b-${si}`}>{inner}</strong>
        );
      } else {
        nodes.push(...inner);
      }
    });

    return nodes;
  };

  // Split the response into paragraphs on blank lines; render each as prose.
  const paragraphs = (text || "")
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter((p) => p.length > 0);

  return (
    <div className="text-modern-dark-text-primary text-base leading-relaxed space-y-3">
      {paragraphs.map((para, i) => (
        <p key={i} className="whitespace-pre-wrap">
          {renderInline(para, `p${i}`)}
        </p>
      ))}
    </div>
  );
}

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

function TypingMessage({
  text,
  onComplete,
  chatContainerRef,
  cancelTypingRef,
  isCanceled,
}) {
  const [displayedText, setDisplayedText] = useState("");
  const typingInterval = useRef(null);

  useEffect(() => {
    if (!text || isCanceled) {
      setDisplayedText((prev) => prev);
      return;
    }

    setDisplayedText("");
    let currentIndex = 0;

    typingInterval.current = setInterval(() => {
      setDisplayedText((prev) => {
        if (currentIndex < text.length) {
          const next = prev + text[currentIndex];
          currentIndex++;

          if (chatContainerRef.current) {
            chatContainerRef.current.scrollTop =
              chatContainerRef.current.scrollHeight;
          }

          return next;
        } else {
          clearInterval(typingInterval.current);
          if (onComplete) onComplete();
          return prev;
        }
      });
    }, 10);

    if (cancelTypingRef) {
      cancelTypingRef.current = () => {
        clearInterval(typingInterval.current);
      };
    }

    return () => clearInterval(typingInterval.current);
  }, [text, onComplete, chatContainerRef, cancelTypingRef, isCanceled]);

  return (
    <div className="max-w-[85%] self-start text-modern-dark-text-primary whitespace-pre-wrap">
      <Formatter text={displayedText} />
    </div>
  );
}

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [isWaiting, setIsWaiting] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const [typingMessage, setTypingMessage] = useState(null);
  const [isCanceled, setIsCanceled] = useState(false);

  const chatContainerRef = useRef(null);
  const pollingIntervalId = useRef(null);
  const cancelTypingRef = useRef(null);
  const sessionId = useRef(
    (() => {
      let id = localStorage.getItem("fw_session_id");
      if (!id) {
        id =
          (window.crypto && window.crypto.randomUUID && window.crypto.randomUUID()) ||
          `sess-${Date.now()}-${Math.random().toString(36).slice(2)}`;
        localStorage.setItem("fw_session_id", id);
      }
      return id;
    })()
  );

  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [messages, isWaiting]);

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
        session_id: sessionId.current,
      });

      const botResponse = res.data.response || "I couldn't generate a response";
      setIsWaiting(false);
      setIsTyping(true);
      setTypingMessage(botResponse);
      setIsCanceled(false);
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
    setMessages((prev) => [
      ...prev,
      {
        role: "bot",
        content: typingMessage,
        timestamp: new Date().toISOString(),
      },
    ]);
    setTypingMessage(null);
  };

  const cancelTyping = () => {
    if (cancelTypingRef.current) {
      cancelTypingRef.current();
      setIsTyping(false);
      setIsCanceled(true);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      isTyping ? cancelTyping() : sendMessage();
    }
  };

  const startPollingUpdateStatus = () => {
    pollingIntervalId.current = setInterval(async () => {
      try {
        const res = await axios.get("http://localhost:5000/api/update-status");
        if (!res.data.updating) {
          setIsUpdating(false);
          clearInterval(pollingIntervalId.current);
        }
      } catch (err) {
        console.error("Failed to get update status:", err);
        clearInterval(pollingIntervalId.current);
        setIsUpdating(false);
      }
    }, 2000);
  };

  const handleUpdateData = async () => {
    setIsUpdating(true);
    try {
      await axios.post("http://localhost:5000/api/update-data");
      startPollingUpdateStatus();
    } catch (err) {
      console.error(err);
      alert("Failed to update data.");
      setIsUpdating(false);
    }
  };

  const isSendDisabled = !isTyping && (!input.trim() || isWaiting || isUpdating);

  return (
    <div className="dark flex flex-col h-screen bg-modern-dark-primary text-modern-dark-text-primary font-sans">
      <header className="h-16 flex justify-between items-center p-4 bg-modern-dark-header-input border-b border-modern-dark-border flex-shrink-0">
        <div className="flex items-center gap-3">
          <img
            src="/logo.png"
            alt="Logo"
            className="w-[60px] h-[60px] object-contain mr-3"
          />
          <span className="text-2xl font-medium">Finance Watcher</span>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setMessages([])}
            disabled={isTyping || isWaiting || isUpdating}
            className="bg-modern-dark-secondary hover:bg-modern-dark-tertiary text-modern-dark-text-primary border border-modern-dark-border px-3 py-1 rounded-lg disabled:opacity-50"
          >
            Clear
          </button>
          <button
            onClick={handleUpdateData}
            disabled={isTyping || isWaiting || isUpdating}
            className="bg-modern-dark-secondary hover:bg-modern-dark-tertiary text-modern-dark-text-primary border border-modern-dark-border px-3 py-1 rounded-lg flex items-center gap-2 disabled:opacity-50"
          >
            {isUpdating ? (
              <>
                <svg
                  className="w-4 h-4 animate-spin text-modern-dark-text-secondary"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                <span>Updating...</span>
              </>
            ) : (
              "Update Data"
            )}
          </button>
        </div>
      </header>

      <div
        className="flex-1 p-6 overflow-y-auto flex flex-col gap-4 bg-modern-dark-secondary scrollbar scrollbar-thumb-modern-dark-header-input scrollbar-track-modern-dark-primary"
        ref={chatContainerRef}
      >
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`max-w-[85%] ${
              msg.role === "user"
                ? "p-4 rounded-xl bg-modern-dark-tertiary text-modern-dark-text-primary self-end rounded-br-none"
                : "self-start text-modern-dark-text-primary whitespace-pre-wrap"
            }`}
            style={msg.role === "bot" ? { padding: 0, margin: 0 } : {}}
          >
            {msg.role === "bot" ? <Formatter text={msg.content} /> : msg.content}
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
        ))}
        {typingMessage && (
          <TypingMessage
            key={messages.length}
            text={typingMessage}
            onComplete={handleTypingComplete}
            chatContainerRef={chatContainerRef}
            cancelTypingRef={cancelTypingRef}
            isCanceled={isCanceled}
          />
        )}
        {isWaiting && <TypingIndicator />}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          isTyping ? cancelTyping() : sendMessage();
        }}
        className="p-4"
      >
        <div className="relative w-[95%] max-w-xl mx-auto">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type your message..."
            disabled={isWaiting || isUpdating}
            rows={1}
            className="w-full p-3 pr-14 rounded-xl border border-modern-dark-border bg-modern-dark-secondary text-modern-dark-text-primary resize-none min-h-[40px] max-h-[120px] focus:outline-none focus:ring-2 focus:ring-modern-dark-accent focus:border-transparent disabled:opacity-50 transition-all"
          />
          <button
            type="button"
            onClick={isTyping ? cancelTyping : sendMessage}
            disabled={isSendDisabled}
            className={`absolute right-3 top-1/2 -translate-y-1/2 h-9 w-9 rounded-full text-white flex items-center justify-center transition-colors ${
              isTyping
                ? "bg-red-600 hover:bg-red-700"
                : "bg-modern-dark-accent hover:bg-modern-dark-accent-hover"
            } ${isSendDisabled ? "bg-modern-dark-tertiary cursor-not-allowed opacity-50" : ""}`}
          >
            {isTyping ? (
              <svg
                className="w-4 h-4"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            ) : isWaiting ? (
              <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
            ) : (
              <svg
                className="w-5 h-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            )}
          </button>
        </div>
        <p className="mt-2 text-xs text-modern-dark-text-secondary text-center max-w-xl mx-auto">
          This is a personal project of Andrei Nanescu. Not financial advice.
        </p>
      </form>
    </div>
  );
}

export default App;
