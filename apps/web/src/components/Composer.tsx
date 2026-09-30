"use client";

import type { Template, TemplateRender } from "@cmc/types";
import { useRef, useState } from "react";

import { api } from "@/lib/api";

export interface ComposerProps {
  conversationId: number;
  templates: Template[];
  disabled?: boolean;
  onSend: (body: string) => Promise<void>;
}

export function Composer({ conversationId, templates, disabled, onSend }: ComposerProps) {
  const [text, setText] = useState("");
  const [missing, setMissing] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);

  async function applyTemplate(template: Template) {
    const rendered = await api.post<TemplateRender>(`/templates/${template.id}/render`, {
      conversation_id: conversationId,
    });
    setText((current) => (current.trim() ? `${current.trimEnd()}\n${rendered.text}` : rendered.text));
    setMissing(rendered.missing_variables);
    area.current?.focus();
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const body = text.trim();
    if (!body || busy) return;
    setBusy(true);
    try {
      await onSend(body);
      setText("");
      setMissing([]);
    } catch {
      // The caller reports the error; keep the text so nothing typed is lost.
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-2" aria-label="Scrivi un messaggio">
      {templates.length > 0 && (
        <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 [scrollbar-width:none]" data-testid="templates">
          {templates.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => void applyTemplate(t)}
              className="shrink-0 rounded-full border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900"
            >
              {t.icon} {t.label}
            </button>
          ))}
        </div>
      )}
      {missing.length > 0 && (
        <p className="text-xs text-amber-700 dark:text-amber-400" role="status">
          Completa prima di inviare: {missing.map((m) => `{{${m}}}`).join(", ")}
        </p>
      )}
      <div className="flex items-end gap-2">
        <textarea
          ref={area}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void submit(e);
          }}
          rows={Math.min(6, Math.max(1, text.split("\n").length))}
          maxLength={4000}
          placeholder="Scrivi…"
          aria-label="Messaggio"
          className="input min-h-11 resize-none py-2.5"
          disabled={disabled}
        />
        <button
          type="submit"
          className="btn-primary shrink-0"
          disabled={disabled || busy || !text.trim() || missing.some((m) => text.includes(`{{${m}}}`))}
        >
          Invia
        </button>
      </div>
    </form>
  );
}
