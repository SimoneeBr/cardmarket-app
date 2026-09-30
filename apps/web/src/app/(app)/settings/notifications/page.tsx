"use client";

import type { NotificationPreference } from "@cmc/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useToast } from "@/components/Toast";
import { PageHeader, Section, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { NOTIFICATION_TYPE } from "@/lib/labels";
import { disablePush, enablePush, getPushState, type PushState } from "@/lib/push";

const PUSH_TEXT: Record<PushState, string> = {
  unsupported: "Questo browser non supporta le notifiche push. Su iPhone: aggiungi l'app alla schermata Home.",
  "disabled-server": "Web Push non è configurato sul server (chiavi VAPID mancanti).",
  denied: "Le notifiche sono bloccate nelle impostazioni del browser.",
  off: "Le notifiche push non sono attive su questo dispositivo.",
  on: "Le notifiche push sono attive su questo dispositivo.",
};

function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative h-7 w-12 shrink-0 rounded-full transition disabled:opacity-40 ${checked ? "bg-brand-600" : "bg-slate-300 dark:bg-slate-700"}`}
    >
      <span className={`absolute top-0.5 size-6 rounded-full bg-white shadow transition ${checked ? "left-5.5" : "left-0.5"}`} />
    </button>
  );
}

export default function NotificationSettingsPage() {
  const client = useQueryClient();
  const toast = useToast();
  const prefs = useQuery({
    queryKey: ["notification-preferences"],
    queryFn: () => api.get<NotificationPreference[]>("/notification-preferences"),
  });
  const save = useMutation({
    mutationFn: (preferences: NotificationPreference[]) =>
      api.put<NotificationPreference[]>("/notification-preferences", { preferences }),
    onSuccess: (data) => client.setQueryData(["notification-preferences"], data),
    onError: (err) => toast(err instanceof ApiError ? err.message : "Errore", "error"),
  });
  const [push, setPush] = useState<PushState | null>(null);

  useEffect(() => {
    getPushState().then(setPush).catch(() => setPush("unsupported"));
  }, []);

  function update(type: NotificationPreference["type"], patch: Partial<NotificationPreference>) {
    const current = prefs.data?.find((p) => p.type === type);
    if (current) save.mutate([{ ...current, ...patch }]);
  }

  async function togglePush() {
    try {
      setPush(push === "on" ? await disablePush() : await enablePush());
    } catch (err) {
      toast(err instanceof Error ? err.message : "Errore push", "error");
    }
  }

  return (
    <div>
      <PageHeader back="/settings" title="Notifiche" />
      <Section title="Push su questo dispositivo">
        <div className="card space-y-3 p-4">
          <p className="text-sm">{push ? PUSH_TEXT[push] : "Verifica…"}</p>
          <div className="flex gap-2">
            {(push === "on" || push === "off") && (
              <button className="btn-primary flex-1" onClick={() => void togglePush()}>
                {push === "on" ? "Disattiva push" : "Attiva push"}
              </button>
            )}
            {push === "on" && (
              <button
                className="btn-secondary"
                onClick={() =>
                  api
                    .post<{ delivered: number }>("/push/test")
                    .then((r) => toast(`Notifica di prova inviata (${r.delivered})`, "success"))
                    .catch((e) => toast(e instanceof Error ? e.message : "Errore", "error"))
                }
              >
                Prova
              </button>
            )}
          </div>
        </div>
      </Section>
      <Section title="Cosa ricevere">
        {prefs.isLoading || !prefs.data ? (
          <Spinner />
        ) : (
          <ul className="card divide-y divide-slate-100 dark:divide-slate-800" data-testid="preferences">
            <li className="flex items-center gap-3 px-4 py-2 text-xs font-semibold text-slate-500 uppercase">
              <span className="flex-1">Evento</span>
              <span className="w-12 text-center">App</span>
              <span className="w-12 text-center">Push</span>
            </li>
            {prefs.data.map((p) => (
              <li key={p.type} className="flex items-center gap-3 px-4 py-3">
                <span className="text-lg">{NOTIFICATION_TYPE[p.type].icon}</span>
                <span className="flex-1 text-sm">{NOTIFICATION_TYPE[p.type].label}</span>
                <Toggle label={`${NOTIFICATION_TYPE[p.type].label} in app`} checked={p.in_app} onChange={(v) => update(p.type, { in_app: v, push: v && p.push })} />
                <Toggle label={`${NOTIFICATION_TYPE[p.type].label} push`} checked={p.push} disabled={!p.in_app} onChange={(v) => update(p.type, { push: v })} />
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
