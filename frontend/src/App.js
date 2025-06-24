import React, { useState, useEffect, useRef } from "react";
import axios from "axios";
import "./App.css";

function TypingIndicator() {
  return (
    <div className="message bot typing-indicator">
      <span className="typing-dot"></span>
      <span className="typing-dot"></span>
      <span className="typing-dot"></span>
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
        setDisplayedText(prev => prev + text[currentIndex]);
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

  return <div className="message bot">{displayedText}</div>;
}

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [isWaiting, setIsWaiting] = useState(false); // New state for API waiting
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
      timestamp: new Date().toISOString()
    };
    setMessages(prev => [...prev, userMessage]);
    setInput("");
    setIsWaiting(true); // Show loading dots while waiting for API

    try {
      const res = await axios.post("http://localhost:5000/api/chat", {
        message: input
      });

      const botResponse = res.data.response || "I couldn't generate a response";
      setIsWaiting(false);
      setIsTyping(true);

      // Add empty bot message to start typing animation
      setMessages(prev => [...prev, {
        role: "bot",
        content: botResponse, // Store full response but display gradually
        timestamp: new Date().toISOString()
      }]);

    } catch (error) {
      setIsWaiting(false);
      setMessages(prev => [...prev, {
        role: "bot",
        content: "Error: Could not get response",
        timestamp: new Date().toISOString()
      }]);
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
    <div className="app">
      <header className="header">
        <h1>My Llama3 Chat</h1>
        <button
          onClick={() => setMessages([])}
          disabled={isTyping || isWaiting}
        >
          Clear
        </button>
      </header>

      <div className="chat-container" ref={chatContainerRef}>
        {messages.map((msg, i) => {
          if (msg.role === "bot" && i === messages.length - 1 && isTyping) {
            return (
              <TypingMessage
                key={i}
                text={msg.content}
                onComplete={handleTypingComplete}
              />
            );
          }
          return (
            <div key={i} className={`message ${msg.role}`}>
              {msg.content}
              <div className="timestamp">
                {new Date(msg.timestamp).toLocaleTimeString()}
              </div>
            </div>
          );
        })}
        {isWaiting && <TypingIndicator />}
      </div>

      <form className="input-container" onSubmit={(e) => {
        e.preventDefault();
        sendMessage();
      }}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type your message..."
          disabled={isTyping || isWaiting}
          rows={1}
        />
        <button
          type="submit"
          disabled={isTyping || isWaiting || !input.trim()}
        >
          {isWaiting ? "..." : isTyping ? "..." : "↑"}
        </button>
      </form>
    </div>
  );
}

export default App;