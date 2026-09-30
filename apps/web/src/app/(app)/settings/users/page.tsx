"use client";

import type { User, UserRole } from "@cmc/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Badge, ErrorState, PageHeader, Section, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { formatAgo } from "@/lib/format";
import { ROLE } from "@/lib/labels";
import { useMe } from "@/lib/queries";

const ROLES: UserRole[] = ["STAFF", "MANAGER", "ADMIN"];

export default function UsersPage() {
  const client = useQueryClient();
  const toast = useToast();
  const { data: me } = useMe();
  const users = useQuery({ queryKey: ["users"], queryFn: () => api.get<User[]>("/admin/users") });
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "STAFF" as UserRole });
  const onError = (err: unknown) => toast(err instanceof ApiError ? err.message : "Errore", "error");
  const refresh = () => void client.invalidateQueries({ queryKey: ["users"] });

  const create = useMutation({
    mutationFn: () => api.post<User>("/admin/users", form),
    onSuccess: () => {
      toast("Utente creato", "success");
      setForm({ name: "", email: "", password: "", role: "STAFF" });
      refresh();
    },
    onError,
  });
  const update = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: Partial<User> & { password?: string } }) => api.patch<User>(`/admin/users/${id}`, patch),
    onSuccess: refresh,
    onError,
  });

  return (
    <div>
      <PageHeader back="/settings" title="Utenti e ruoli" />
      <Section title="Utenti">
        {users.isLoading ? <Spinner /> : users.error ? <ErrorState error={users.error} /> : (
          <ul className="card divide-y divide-slate-100 dark:divide-slate-800" data-testid="users-list">
            {users.data?.map((u) => (
              <li key={u.id} className="space-y-2 px-4 py-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate font-medium">
                      {u.name} {!u.active && <Badge tone="danger">disabilitato</Badge>}
                    </p>
                    <p className="truncate text-sm text-slate-500">{u.email} · ultimo accesso {formatAgo(u.last_login_at)}</p>
                  </div>
                </div>
                {u.id !== me?.id && (
                  <div className="flex flex-wrap gap-2">
                    <select aria-label={`Ruolo di ${u.name}`} className="input w-auto min-h-9 py-1 text-sm" value={u.role} onChange={(e) => update.mutate({ id: u.id, patch: { role: e.target.value as UserRole } })}>
                      {ROLES.map((r) => <option key={r} value={r}>{ROLE[r]}</option>)}
                    </select>
                    <button className="btn-secondary min-h-9 text-xs" onClick={() => update.mutate({ id: u.id, patch: { active: !u.active } })}>
                      {u.active ? "Disabilita" : "Riattiva"}
                    </button>
                    <button
                      className="btn-secondary min-h-9 text-xs"
                      onClick={() => {
                        const password = window.prompt(`Nuova password per ${u.email} (min. 10 caratteri)`);
                        if (password) update.mutate({ id: u.id, patch: { password } });
                      }}
                    >
                      Reimposta password
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title="Nuovo utente">
        <form className="card space-y-3 p-4" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <input className="input" placeholder="Nome" aria-label="Nome" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input className="input" type="email" placeholder="Email" aria-label="Email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <input className="input" type="password" autoComplete="new-password" placeholder="Password iniziale (min. 10)" aria-label="Password" minLength={10} required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          <select className="input" aria-label="Ruolo" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as UserRole })}>
            {ROLES.map((r) => <option key={r} value={r}>{ROLE[r]}</option>)}
          </select>
          <button className="btn-primary w-full" disabled={create.isPending}>Crea utente</button>
        </form>
      </Section>
    </div>
  );
}
