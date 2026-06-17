"use client";

import { useEffect, useState, useRef } from "react";
import ReactMarkdown from "react-markdown";
import { apiFetch, apiStream } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";

const SUGGESTED = [
  "Where is my money going?",
  "What subscriptions do I have?",
  "Can I afford to hire?",
  "What is my forecast for next month?",
];

interface Session {
  id: string;
  title: string | null;
}

interface Message {
  id?: string;
  role: "user" | "assistant";
  content: string;
}

export default function ChatPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSession, setActiveSession] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    apiFetch<Session[]>("/chat/sessions").then(setSessions).catch(() => {});
  }, []);

  useEffect(() => {
    if (!activeSession) return;
    apiFetch<Message[]>(`/chat/sessions/${activeSession}/messages`).then(setMessages).catch(() => {});
  }, [activeSession]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function newChat() {
    const session = await apiFetch<Session>("/chat/sessions", {
      method: "POST",
      body: JSON.stringify({ title: "New Chat" }),
    });
    setSessions((s) => [session, ...s]);
    setActiveSession(session.id);
    setMessages([]);
  }

  async function sendMessage(text: string) {
    if (!text.trim() || streaming) return;
    let sessionId = activeSession;
    if (!sessionId) {
      const session = await apiFetch<Session>("/chat/sessions", {
        method: "POST",
        body: JSON.stringify({ title: text.slice(0, 40) }),
      });
      sessionId = session.id;
      setActiveSession(sessionId);
      setSessions((s) => [session, ...s]);
    }

    setMessages((m) => [...m, { role: "user", content: text }]);
    setInput("");
    setStreaming(true);

    const assistantMsg: Message = { role: "assistant", content: "" };
    setMessages((m) => [...m, assistantMsg]);

    try {
      const res = await apiStream(`/chat/sessions/${sessionId}/messages`, { content: text });
      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) return;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value);
        assistantMsg.content += chunk;
        setMessages((m) => {
          const copy = [...m];
          copy[copy.length - 1] = { ...assistantMsg };
          return copy;
        });
      }
    } catch {
      setMessages((m) => [
        ...m.slice(0, -1),
        { role: "assistant", content: "Sorry, I couldn't process that. Check your API configuration." },
      ]);
    } finally {
      setStreaming(false);
    }
  }

  return (
    <div className="flex h-[calc(100vh-8rem)] gap-4">
      <Card className="w-64 flex-shrink-0 overflow-y-auto p-3">
        <Button className="mb-3 w-full" onClick={newChat}>
          New Chat
        </Button>
        {sessions.map((s) => (
          <button
            key={s.id}
            onClick={() => setActiveSession(s.id)}
            className={`mb-1 w-full rounded-lg px-3 py-2 text-left text-sm ${
              activeSession === s.id ? "bg-blue-600/20 text-blue-400" : "text-slate-400 hover:bg-slate-800"
            }`}
          >
            {s.title || "Chat"}
          </button>
        ))}
      </Card>

      <div className="flex flex-1 flex-col rounded-2xl border border-slate-800 bg-slate-900/30">
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {messages.length === 0 && (
            <div className="space-y-2">
              <p className="text-slate-400">Ask anything about your finances:</p>
              {SUGGESTED.map((q) => (
                <button
                  key={q}
                  onClick={() => sendMessage(q)}
                  className="block w-full rounded-lg border border-slate-700 px-4 py-3 text-left text-sm text-slate-300 hover:bg-slate-800"
                >
                  {q}
                </button>
              ))}
            </div>
          )}
          {messages.map((msg, i) => (
            <div
              key={i}
              className={`max-w-[80%] rounded-2xl px-4 py-3 ${
                msg.role === "user" ? "ml-auto bg-blue-600 text-white" : "bg-slate-800 text-slate-200"
              }`}
            >
              {msg.role === "assistant" ? (
                <div className="prose prose-invert prose-sm max-w-none">
                  <ReactMarkdown>{msg.content}</ReactMarkdown>
                </div>
              ) : (
                msg.content
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            sendMessage(input);
          }}
          className="flex gap-2 border-t border-slate-800 p-4"
        >
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about your finances..."
            disabled={streaming}
          />
          <Button type="submit" disabled={streaming}>
            Send
          </Button>
        </form>
      </div>
    </div>
  );
}
