"use client";

import {
  Box, Chip, CircularProgress, Divider, Drawer, IconButton, Stack, TextField,
  Tooltip, Typography,
} from "@mui/material";
import {
  AlertCircle, BrainCog, FileText, Network, RotateCcw, Send, Sparkles, Trash2, X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/lib/api";

/**
 * Ask-the-brain chat drawer — MUI-styled, slide-in from the right.
 *
 * Talks to /api/chat which routes each question to either:
 *   - graph    (deterministic, <100ms, no LLM cost) — for relationship
 *              questions like "list vendors", "documents for account X"
 *   - hybrid   (graph context + RAG chunks + LLM synthesis, ~3-10s) — for
 *              everything else
 * Each assistant message exposes which route it took, the elapsed time,
 * and the document IDs that were retrieved so the user can audit grounding.
 *
 * Design rules:
 *   - 8px grid spacing throughout (matches workspace + brain pages)
 *   - WCAG: focus-visible ring on every interactive element, role="dialog"
 *     on the drawer (MUI Drawer handles this), aria-live on the message
 *     list so screen readers announce streaming additions.
 *   - History semantics: the backend's prompt-builder appends the current
 *     `question` AFTER the history block, so we MUST send the history
 *     WITHOUT the current question — otherwise the user message ends up
 *     duplicated in the LLM prompt.
 */

type Message = {
  role: "user" | "assistant";
  content: string;
  route?: "graph" | "hybrid" | "llm";
  citations?: string[];
  elapsedMs?: number;
  error?: boolean;
  at: number;
};

/** Starter prompts shown when the conversation is empty. Picked to cover
 *  both routing branches so the user immediately gets a sense of what the
 *  brain can answer. Tweak these to fit your tenant's primary use cases —
 *  the bot's "first impression" lives here. */
const SUGGESTED_QUESTIONS: { label: string; icon: typeof Network }[] = [
  { label: "Show me all vendors in the corpus",                icon: Network },
  { label: "Which contracts expire in the next 30 days?",      icon: Sparkles },
  { label: "Summarize this month's spend by vendor",           icon: BrainCog },
  { label: "What anomalies were flagged in last week's batches?", icon: AlertCircle },
];

export function ChatDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to the latest message whenever the list grows or the
  // assistant finishes typing. Smooth scrolling matches MUI's transitions
  // — sets the rhythm even though the chat itself isn't streaming yet.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, busy]);

  // Focus the input each time the drawer opens — saves an extra click.
  useEffect(() => {
    if (open) {
      const t = setTimeout(() => inputRef.current?.focus(), 200);
      return () => clearTimeout(t);
    }
  }, [open]);

  const sendText = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setBusy(true);

    // Capture the conversation BEFORE this turn — that's the history we
    // send to the backend. The current question goes in the `question`
    // field; sending it in both places would duplicate it in the prompt.
    const priorHistory = messages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    const userMsg: Message = { role: "user", content: trimmed, at: Date.now() };
    setMessages((prev) => [...prev, userMsg]);
    setDraft("");

    try {
      const reply = await api.chat(trimmed, priorHistory);
      setMessages((prev) => [...prev, {
        role: "assistant",
        content: reply.answer,
        route: reply.route,
        citations: reply.citations,
        elapsedMs: reply.elapsed_ms,
        at: Date.now(),
      }]);
    } catch (e) {
      // Translate the most common failure modes into human-language hints
      // so the analyst knows what to do next. Anything else falls through
      // to the raw message — better to show too much than too little.
      const raw = (e as Error).message;
      let friendly = raw;
      if (/\b401\b/.test(raw)) {
        friendly = "I need a tenant API key to query your corpus. Sign in on the /login page with your tenant key — admin keys aren't enough for chat because the knowledge graph is RLS-scoped per tenant.";
      } else if (/timed out|backend is running/i.test(raw)) {
        friendly = "The backend didn't respond in 45 seconds. The LLM may be rate-limited, or mdi-server isn't running. Try again, or ask a relationship question (e.g. \"list vendors\") — those skip the LLM and answer in <100ms.";
      } else if (/Network error/i.test(raw)) {
        friendly = "I couldn't reach the backend at all. Check that mdi-server is running on its expected port.";
      }
      setMessages((prev) => [...prev, {
        role: "assistant",
        content: friendly,
        error: true,
        at: Date.now(),
      }]);
    } finally {
      setBusy(false);
    }
  }, [busy, messages]);

  const clearConversation = useCallback(() => {
    if (busy) return;
    setMessages([]);
    setDraft("");
    inputRef.current?.focus();
  }, [busy]);

  const lastAssistantIdx = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant") return i;
    }
    return -1;
  }, [messages]);

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      // Keep mounted so React Query caches inside the drawer (if added
      // later) survive open/close cycles. Cheap — it's one tree.
      keepMounted
      PaperProps={{
        sx: {
          width: { xs: "100%", sm: 480 },
          maxWidth: "100vw",
          // The drawer is a long vertical pane — flex layout pins the
          // header at top and the input at bottom; the message list
          // scrolls in the middle.
          display: "flex",
          flexDirection: "column",
          bgcolor: "background.default",
        },
      }}
    >
      {/* ─── Header ─────────────────────────────────────────────────── */}
      <Box
        sx={{
          px: 3, py: 2,
          borderBottom: 1, borderColor: "divider",
          display: "flex", alignItems: "center", justifyContent: "space-between",
          gap: 2,
        }}
      >
        <Stack direction="row" alignItems="center" spacing={1.5} sx={{ minWidth: 0 }}>
          <Box
            sx={{
              width: 32, height: 32, borderRadius: 1.5,
              background: "linear-gradient(135deg, #6366F1, #4338CA)",
              color: "white",
              display: "flex", alignItems: "center", justifyContent: "center",
              flexShrink: 0,
            }}
            aria-hidden
          >
            <BrainCog size={18} />
          </Box>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="h4" sx={{ fontWeight: 700, lineHeight: 1.2 }}>
              Ask the brain
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", lineHeight: 1.2 }}>
              Grounded in your knowledge graph + document corpus
            </Typography>
          </Box>
        </Stack>
        <Stack direction="row" spacing={0.5} alignItems="center" sx={{ flexShrink: 0 }}>
          <Tooltip title="Clear conversation">
            <span>
              <IconButton
                onClick={clearConversation}
                disabled={busy || messages.length === 0}
                size="small"
                aria-label="Clear conversation"
              >
                <Trash2 size={16} />
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip title="Close">
            <IconButton onClick={onClose} size="small" aria-label="Close drawer">
              <X size={18} />
            </IconButton>
          </Tooltip>
        </Stack>
      </Box>

      {/* ─── Message list ────────────────────────────────────────────── */}
      <Box
        ref={scrollRef}
        role="log"
        aria-live="polite"
        aria-label="Chat conversation"
        sx={{
          flex: 1,
          overflowY: "auto",
          px: 3, py: 2.5,
          // Subtle background tint so the bubbles read clearly.
          bgcolor: (t) => t.palette.mode === "dark" ? "background.default" : "rgba(241,245,249,0.5)",
        }}
      >
        {messages.length === 0 ? (
          <EmptyState onPick={(text) => void sendText(text)} disabled={busy} />
        ) : (
          <Stack spacing={2}>
            {messages.map((m, i) => (
              <MessageBubble
                key={m.at + ":" + i}
                message={m}
                isLastAssistant={i === lastAssistantIdx}
              />
            ))}
            {busy && <ThinkingBubble />}
          </Stack>
        )}
      </Box>

      <Divider />

      {/* ─── Composer ────────────────────────────────────────────────── */}
      <Box sx={{ px: 2.5, py: 2, bgcolor: "background.paper" }}>
        <Stack direction="row" spacing={1} alignItems="flex-end">
          <TextField
            inputRef={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              // Enter sends, Shift+Enter newlines — same convention as
              // every modern chat surface (Slack, Discord, ChatGPT).
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void sendText(draft);
              }
            }}
            placeholder={messages.length === 0
              ? "Ask anything about your documents…"
              : "Follow up…"
            }
            multiline
            maxRows={5}
            fullWidth
            size="small"
            disabled={busy}
            aria-label="Type your question"
            sx={{
              "& .MuiOutlinedInput-root": {
                borderRadius: 2,
                bgcolor: "background.default",
              },
            }}
          />
          <Tooltip title="Send (Enter)">
            <span>
              <IconButton
                onClick={() => void sendText(draft)}
                disabled={busy || !draft.trim()}
                aria-label="Send message"
                sx={{
                  background: "linear-gradient(135deg, #6366F1, #4338CA)",
                  color: "white",
                  width: 40, height: 40,
                  flexShrink: 0,
                  "&:hover": {
                    background: "linear-gradient(135deg, #4F46E5, #312E81)",
                  },
                  "&.Mui-disabled": {
                    background: (t) => t.palette.action.disabledBackground,
                    color: (t) => t.palette.action.disabled,
                  },
                }}
              >
                <Send size={16} />
              </IconButton>
            </span>
          </Tooltip>
        </Stack>
        <Typography
          variant="caption"
          sx={{ display: "block", mt: 1, color: "text.secondary", textAlign: "center" }}
        >
          Enter to send · Shift+Enter for newline
        </Typography>
      </Box>
    </Drawer>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Empty state
// ─────────────────────────────────────────────────────────────────────────
function EmptyState({ onPick, disabled }: { onPick: (text: string) => void; disabled: boolean }) {
  return (
    <Stack spacing={3} sx={{ pt: 1 }}>
      <Box>
        <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
          Hi 👋 — I have access to every document this tenant has ingested.
        </Typography>
        <Typography variant="body2" color="text.secondary">
          I can answer questions about vendors, contracts, spend trends, anomalies,
          and any field that was extracted from your documents. Try one of these,
          or type your own:
        </Typography>
      </Box>
      <Stack spacing={1}>
        {SUGGESTED_QUESTIONS.map(({ label, icon: Icon }) => (
          <Box
            key={label}
            component="button"
            onClick={() => onPick(label)}
            disabled={disabled}
            sx={{
              width: "100%",
              textAlign: "left",
              border: 1, borderColor: "divider", borderRadius: 2,
              bgcolor: "background.paper",
              px: 2, py: 1.5,
              cursor: "pointer",
              display: "flex", alignItems: "center", gap: 1.5,
              transition: "all .15s ease",
              "&:hover:not(:disabled)": {
                borderColor: "primary.main",
                bgcolor: (t) => t.palette.mode === "dark"
                  ? "rgba(99,102,241,.12)" : "rgba(99,102,241,.04)",
                transform: "translateY(-1px)",
                boxShadow: 1,
              },
              "&:focus-visible": {
                outline: "2px solid",
                outlineColor: "primary.main",
                outlineOffset: 2,
              },
              "&:disabled": { opacity: 0.5, cursor: "not-allowed" },
            }}
          >
            <Box sx={{ color: "primary.main", flexShrink: 0 }}>
              <Icon size={16} />
            </Box>
            <Typography variant="body2" sx={{ flex: 1, fontWeight: 500 }}>
              {label}
            </Typography>
          </Box>
        ))}
      </Stack>
      <Box
        sx={{
          mt: 1, p: 1.5,
          bgcolor: (t) => t.palette.mode === "dark" ? "rgba(99,102,241,.10)" : "rgba(99,102,241,.06)",
          border: 1, borderColor: "primary.main", borderRadius: 1.5,
          opacity: 0.85,
        }}
      >
        <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
          <strong>Heads up:</strong> answers are grounded in your indexed documents.
          If the brain hasn&apos;t seen something yet, it&apos;ll say so rather than guess.
        </Typography>
      </Box>
    </Stack>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Bubbles
// ─────────────────────────────────────────────────────────────────────────
function MessageBubble({ message, isLastAssistant }: { message: Message; isLastAssistant: boolean }) {
  const isUser = message.role === "user";
  const isError = !!message.error;
  return (
    <Box sx={{ display: "flex", justifyContent: isUser ? "flex-end" : "flex-start" }}>
      <Box sx={{ maxWidth: "88%", display: "flex", flexDirection: "column", alignItems: isUser ? "flex-end" : "flex-start" }}>
        <Box
          sx={{
            px: 2, py: 1.25,
            borderRadius: 2,
            bgcolor: isUser
              ? (t) => t.palette.mode === "dark" ? "primary.dark" : "primary.main"
              : isError
                ? (t) => t.palette.mode === "dark" ? "rgba(220,38,38,.18)" : "#FEE2E2"
                : "background.paper",
            color: isUser ? "primary.contrastText" : isError ? "error.main" : "text.primary",
            border: isUser ? 0 : 1,
            borderColor: isError ? "error.main" : "divider",
            boxShadow: isUser ? 1 : 0,
            // Long answers benefit from a line-height that's easy to scan.
            lineHeight: 1.55,
            // Preserve whitespace + line breaks from the LLM (it sometimes
            // returns bullet lists separated by \n).
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {isError && (
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5, fontWeight: 600 }}>
              <AlertCircle size={14} />
              <Typography variant="caption" sx={{ fontWeight: 700 }}>
                Couldn&apos;t reach the brain
              </Typography>
            </Stack>
          )}
          <Typography variant="body2" component="span" sx={{ whiteSpace: "inherit", wordBreak: "inherit" }}>
            {message.content}
          </Typography>
        </Box>

        {/* Assistant metadata footer — route + elapsed + citations. */}
        {!isUser && !isError && (message.route || message.elapsedMs != null || (message.citations?.length ?? 0) > 0) && (
          <Stack
            direction="row"
            spacing={1}
            alignItems="center"
            useFlexGap
            flexWrap="wrap"
            sx={{ mt: 0.75, px: 0.5 }}
          >
            {message.route && (
              <Tooltip
                title={
                  message.route === "graph"
                    ? "Answered from the knowledge graph (no LLM call)."
                    : "Answered by the LLM with graph + retrieved document chunks as context."
                }
              >
                <Chip
                  icon={message.route === "graph" ? <Network size={11} /> : <Sparkles size={11} />}
                  label={message.route}
                  size="small"
                  variant="outlined"
                  sx={{ height: 20, fontSize: 10.5, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.4 }}
                />
              </Tooltip>
            )}
            {message.elapsedMs != null && (
              <Typography variant="caption" color="text.secondary" sx={{ fontVariantNumeric: "tabular-nums" }}>
                {message.elapsedMs < 1000
                  ? `${message.elapsedMs} ms`
                  : `${(message.elapsedMs / 1000).toFixed(1)} s`}
              </Typography>
            )}
            {(message.citations?.length ?? 0) > 0 && (
              <Stack direction="row" spacing={0.5} alignItems="center" useFlexGap flexWrap="wrap">
                <FileText size={11} style={{ opacity: 0.5 }} />
                {message.citations!.slice(0, 3).map((id) => (
                  <Tooltip title={`Document ${id}`} key={id}>
                    <Chip
                      label={id.slice(0, 8)}
                      size="small"
                      sx={{
                        height: 20, fontSize: 10.5, fontFamily: "monospace",
                        cursor: "pointer",
                        "&:hover": { bgcolor: "primary.main", color: "primary.contrastText" },
                      }}
                      onClick={() => {
                        // Future: route to /workspace?doc=<id> for drill-down.
                        // For now, copy to clipboard so analysts can paste it.
                        if (typeof navigator !== "undefined" && navigator.clipboard) {
                          void navigator.clipboard.writeText(id);
                        }
                      }}
                    />
                  </Tooltip>
                ))}
                {message.citations!.length > 3 && (
                  <Typography variant="caption" color="text.secondary">
                    +{message.citations!.length - 3} more
                  </Typography>
                )}
              </Stack>
            )}
          </Stack>
        )}

        {/* Retry affordance on the last assistant error — bubbles down to
            the same backend with the same prior turn, so analyst can
            recover from a transient hiccup without retyping. */}
        {!isUser && isError && isLastAssistant && (
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 0.75, px: 0.5 }}>
            <RotateCcw size={11} style={{ opacity: 0.5 }} />
            <Typography variant="caption" color="text.secondary">
              Try a more specific question, or check that the backend is reachable.
            </Typography>
          </Stack>
        )}
      </Box>
    </Box>
  );
}

function ThinkingBubble() {
  return (
    <Box sx={{ display: "flex", justifyContent: "flex-start" }}>
      <Stack
        direction="row" spacing={1.5} alignItems="center"
        sx={{
          px: 2, py: 1.25, borderRadius: 2,
          bgcolor: "background.paper", border: 1, borderColor: "divider",
        }}
      >
        <CircularProgress size={14} thickness={5} />
        <Typography variant="body2" color="text.secondary">
          Thinking…
        </Typography>
      </Stack>
    </Box>
  );
}
