import React, { useState, useRef, useEffect } from "react";
import { Send, MessageSquare } from "lucide-react";
import { useStore } from "../../store/useStore";
import { sendChatMessage } from "../../services/api";

// ─── Typing indicator ──────────────────────────────────────────────────────
const TypingIndicator: React.FC = () => (
  <div className="flex items-start gap-2 px-4 py-2">
    <div className="bg-parcl-surface border border-parcl-border rounded-2xl rounded-bl-sm px-4 py-2 max-w-[85%]">
      <div className="flex items-center gap-1">
        <div className="w-1.5 h-1.5 rounded-full bg-parcl-text-muted animate-bounce [animation-delay:0ms]" />
        <div className="w-1.5 h-1.5 rounded-full bg-parcl-text-muted animate-bounce [animation-delay:150ms]" />
        <div className="w-1.5 h-1.5 rounded-full bg-parcl-text-muted animate-bounce [animation-delay:300ms]" />
      </div>
    </div>
  </div>
);

// ─── Component ─────────────────────────────────────────────────────────────
const ChatPanel: React.FC = () => {
  const chatMessages = useStore((s) => s.chatMessages);
  const isChatLoading = useStore((s) => s.isChatLoading);
  const selectedProperty = useStore((s) => s.selectedProperty);
  const addChatMessage = useStore((s) => s.addChatMessage);
  const setIsChatLoading = useStore((s) => s.setIsChatLoading);

  const [inputValue, setInputValue] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages, isChatLoading]);

  const handleSend = async () => {
    const text = inputValue.trim();
    if (!text || isChatLoading) return;

    setInputValue("");

    // Add user message
    addChatMessage({
      role: "user",
      content: text,
      timestamp: new Date().toISOString(),
    });

    setIsChatLoading(true);

    try {
      const response = await sendChatMessage(text, selectedProperty?.id);

      addChatMessage({
        role: "assistant",
        content: response.content,
        timestamp: new Date().toISOString(),
        sources: response.sources,
        suggested_questions: response.suggested_questions,
      });
    } catch (err) {
      addChatMessage({
        role: "assistant",
        content:
          "Sorry, I encountered an error processing your request. Please try again.",
        timestamp: new Date().toISOString(),
      });
    } finally {
      setIsChatLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleSuggestedQuestion = (question: string) => {
    setInputValue(question);
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
        {chatMessages.length === 0 && !isChatLoading ? (
          <div className="flex flex-col items-center justify-center h-full text-parcl-text-muted px-4 py-8">
            <MessageSquare className="w-7 h-7 mb-2 opacity-40" />
            <p className="text-xs text-center leading-relaxed">
              Ask me anything about properties, permits, or neighborhoods in
              your area.
            </p>
          </div>
        ) : (
          <>
            {chatMessages.map((msg, idx) => (
              <div key={idx}>
                {msg.role === "user" ? (
                  /* User message */
                  <div className="flex justify-end">
                    <div className="bg-parcl-accent text-white rounded-2xl rounded-br-sm px-4 py-2 max-w-[85%] text-xs">
                      {msg.content}
                    </div>
                  </div>
                ) : (
                  /* Assistant message */
                  <div className="flex justify-start">
                    <div>
                      <div className="bg-parcl-surface border border-parcl-border rounded-2xl rounded-bl-sm px-4 py-2 max-w-[85%] text-xs text-parcl-text">
                        {msg.content}
                      </div>

                      {/* Sources */}
                      {msg.sources && msg.sources.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1.5 ml-1">
                          {msg.sources.map((source, sIdx) => (
                            <span
                              key={sIdx}
                              className="inline-flex items-center px-1.5 py-0.5 text-[9px] text-parcl-accent bg-parcl-accent/5 border border-parcl-accent/20 rounded cursor-pointer hover:bg-parcl-accent/10 transition-colors"
                              title={source.address}
                            >
                              {source.permit_number || source.address}
                            </span>
                          ))}
                        </div>
                      )}

                      {/* Suggested questions */}
                      {msg.suggested_questions &&
                        msg.suggested_questions.length > 0 && (
                          <div className="flex flex-wrap mt-2 ml-1">
                            {msg.suggested_questions.map((q, qIdx) => (
                              <button
                                key={qIdx}
                                onClick={() => handleSuggestedQuestion(q)}
                                className="inline-flex px-2 py-1 text-[10px] bg-parcl-surface border border-parcl-border rounded-full hover:border-parcl-accent cursor-pointer transition-colors mr-1 mb-1 text-parcl-text-dim"
                              >
                                {q}
                              </button>
                            ))}
                          </div>
                        )}
                    </div>
                  </div>
                )}
              </div>
            ))}

            {/* Typing indicator */}
            {isChatLoading && <TypingIndicator />}
          </>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="flex-shrink-0 px-3 py-2 border-t border-parcl-border">
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about properties, permits..."
            className="bg-parcl-surface border border-parcl-border rounded-lg px-3 py-2 text-xs text-parcl-text placeholder-parcl-text-muted focus:border-parcl-accent focus:outline-none w-full"
            disabled={isChatLoading}
          />
          <button
            onClick={handleSend}
            disabled={!inputValue.trim() || isChatLoading}
            className={`flex-shrink-0 p-2 rounded-lg transition-colors ${
              inputValue.trim() && !isChatLoading
                ? "bg-parcl-accent text-white hover:bg-parcl-accent-dim cursor-pointer"
                : "bg-parcl-surface text-parcl-text-muted cursor-not-allowed"
            }`}
          >
            <Send className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
};

export default ChatPanel;
