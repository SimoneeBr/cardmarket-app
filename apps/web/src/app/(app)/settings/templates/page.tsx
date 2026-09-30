"use client";

import type { Template, TemplateInput } from "@cmc/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Badge, ConfirmButton, ErrorState, PageHeader, Section, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { keys } from "@/lib/queries";

const EMPTY: TemplateInput = { key: "", label: "", icon: "", body: "", position: 0, active: true };

function TemplateForm({ initial, onDone }: { initial: TemplateInput & { id?: number }; onDone: () => void }) {
  const client = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState(initial);
  const save = useMutation({
    mutationFn: () => (initial.id ? api.put(`/templates/${initial.id}`, form) : api.post("/templates", form)),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.templates });
      void client.invalidateQueries({ queryKey: ["templates-admin"] });
      toast("Template salvato", "success");
      onDone();
    },
    onError: (err) => toast(err instanceof ApiError ? err.message : "Errore", "error"),
  });
  return (
    <form className="card space-y-3 p-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <div className="grid grid-cols-[4rem_1fr] gap-2">
        <input className="input text-center" placeholder="🙂" aria-label="Icona" maxLength={4} value={form.icon} onChange={(e) => setForm({ ...form, icon: e.target.value })} />
        <input className="input" placeholder="Etichetta" aria-label="Etichetta" required value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} />
      </div>
      <input className="input" placeholder="chiave_univoca" aria-label="Chiave" pattern="[a-z0-9_\-]+" required value={form.key} onChange={(e) => setForm({ ...form, key: e.target.value })} />
      <textarea className="input min-h-28 py-2" aria-label="Testo" required value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} />
      <p className="text-xs text-slate-500">
        Variabili: {"{{buyer_name}} {{order_id}} {{tracking_number}} {{total_amount}} {{shop_name}}"}
      </p>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} /> Attivo
      </label>
      <div className="flex gap-2">
        <button className="btn-primary flex-1" disabled={save.isPending}>Salva</button>
        <button type="button" className="btn-secondary" onClick={onDone}>Chiudi</button>
      </div>
    </form>
  );
}

export default function TemplatesPage() {
  const client = useQueryClient();
  const toast = useToast();
  const list = useQuery({ queryKey: ["templates-admin"], queryFn: () => api.get<Template[]>("/templates", { include_inactive: true }) });
  const [editing, setEditing] = useState<(TemplateInput & { id?: number }) | null>(null);
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/templates/${id}`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["templates-admin"] });
      void client.invalidateQueries({ queryKey: keys.templates });
    },
    onError: (err) => toast(err instanceof ApiError ? err.message : "Errore", "error"),
  });

  return (
    <div>
      <PageHeader back="/settings" title="Template messaggi" action={<button className="btn-primary min-h-9 px-3 text-xs" onClick={() => setEditing({ ...EMPTY, position: list.data?.length ?? 0 })}>+ Nuovo</button>} />
      {editing && <div className="mb-4"><TemplateForm key={editing.id ?? "new"} initial={editing} onDone={() => setEditing(null)} /></div>}
      <Section title="Template">
        {list.isLoading ? <Spinner /> : list.error ? <ErrorState error={list.error} /> : (
          <ul className="card divide-y divide-slate-100 dark:divide-slate-800">
            {list.data?.map((t) => (
              <li key={t.id} className="px-4 py-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-medium">{t.icon} {t.label} {!t.active && <Badge>inattivo</Badge>}</p>
                  <div className="flex gap-2">
                    <button className="btn-secondary min-h-9 text-xs" onClick={() => setEditing(t)}>Modifica</button>
                    <ConfirmButton className="btn-secondary min-h-9 text-xs" label="Elimina" confirmLabel="Sicuro?" onConfirm={() => remove.mutate(t.id)} />
                  </div>
                </div>
                <p className="mt-1 text-sm whitespace-pre-wrap text-slate-500">{t.body}</p>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
