"use client";

import { useState } from "react";

import { useToast } from "@/components/Toast";
import { PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";

export default function ProfilePage() {
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (next !== confirm) {
      toast("Le password non coincidono", "error");
      return;
    }
    setBusy(true);
    try {
      await api.post("/me/password", { current_password: current, new_password: next });
      toast("Password aggiornata. Le altre sessioni sono state disconnesse.", "success");
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Errore", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader back="/settings" title="Profilo" />
      <form onSubmit={submit} className="card space-y-3 p-4">
        <p className="font-semibold">Cambia password</p>
        <input className="input" type="password" autoComplete="current-password" placeholder="Password attuale" aria-label="Password attuale" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        <input className="input" type="password" autoComplete="new-password" placeholder="Nuova password (min. 10)" aria-label="Nuova password" minLength={10} value={next} onChange={(e) => setNext(e.target.value)} required />
        <input className="input" type="password" autoComplete="new-password" placeholder="Ripeti nuova password" aria-label="Ripeti nuova password" minLength={10} value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
        <button className="btn-primary w-full" disabled={busy}>
          Aggiorna password
        </button>
      </form>
    </div>
  );
}
