"use client";

import { Send, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Spinner } from "./ui";

type Message = { role: "user" | "assistant"; content: string };

/**
 * Slide-in chat drawer accessible from any page. Talks to /api/chat which
 * is the existing RAG-over-tenant-corpus endpoint (Chat layer in MDI's
 * brain). Citations come back as document_ids; clicking them would
 * route to /workspace?doc=<id> (TODO once Workspace's detail view lands).
 *
 * Why a drawer not a dedicated /chat route: asking the brain a question
 * almost always happens IN CONTEXT of something else (a pattern card,
 * an anomaly, a recent batch). A route change would lose that context.
 */
export function ChatDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll on new message — drawer stays pinned to the latest.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length]);

  const send = async () => {
    const text = draft.trim();
    if (!text || busy) return;
    const next: Message[] = [...messages, { role: "user", content: text }];
    setMessages(next);
    setDraft("");
    setBusy(true);
    try {
      const reply = await api.chat(text, next);
      setMessages([...next, { role: "assistant", content: reply.answer }]);
    } catch (e) {
      setMessages([...next, {
        role: "assistant",
        content: `(error talking to /chat: ${(e as Error).message})`,
      }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {/* Backdrop — clicking outside the drawer closes it */}
      <div
        className={cn(
          "fixed inset-0 bg-black/30 transition-opacity z-40",
          open ? "opacity-100" : "opacity-0 pointer-events-none",
        )}
        onClick={onClose}
      />
      <div
        className={cn(
          "fixed right-0 top-0 h-full w-full sm:w-[420px] z-50",
          "bg-[rgb(var(--surface))] border-l border-[rgb(var(--border))]",
          "transform transition-transform shadow-xl flex flex-col",
          open ? "translate-x-0" : "translate-x-full",
        )}
        aria-hidden={!open}
      >
        <header className="h-14 px-4 border-b border-[rgb(var(--border))] flex items-center justify-between">
          <div className="font-semibold">Ask the brain</div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </Button>
        </header>

        <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
          {messages.length === 0 && (
            <div className="text-sm text-[rgb(var(--fg-muted))]">
              Try: <em>“what vendors are dominating last week's batches?”</em>{" "}
              or <em>“which contracts expire next 30 days?”</em>
            </div>
          )}
          {messages.map((m, i) => (
            <div
              key={i}
              className={cn(
                "max-w-[85%] rounded-lg px-3 py-2 text-sm",
                m.role === "user"
                  ? "ml-auto bg-brand-600 text-white"
                  : "bg-[rgb(var(--surface-muted))]",
              )}
            >
              {m.content}
            </div>
          ))}
          {busy && <Spinner />}
        </div>

        <div className="p-3 border-t border-[rgb(var(--border))] flex gap-2">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            placeholder="Ask anything about your documents…"
            className={cn(
              "flex-1 h-9 rounded-md border border-[rgb(var(--border))] px-3 text-sm",
              "bg-[rgb(var(--surface))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500",
            )}
          />
          <Button onClick={send} disabled={busy || !draft.trim()} size="sm">
            <Send className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </>
  );
}
