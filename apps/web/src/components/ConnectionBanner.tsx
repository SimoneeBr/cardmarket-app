"use client";

import type { Connection } from "@cmc/types";
import Link from "next/link";

import { formatAgo } from "@/lib/format";
import { CONNECTION_STATUS, ERROR_CODE } from "@/lib/labels";
import { useConnection, useMe } from "@/lib/queries";

const NEEDS_HUMAN = new Set(["AUTH_REQUIRED", "SESSION_EXPIRED", "ERROR", "DISCONNECTED"]);

export function ConnectionLine({ connection }: { connection: Connection }) {
  const meta = CONNECTION_STATUS[connection.status];
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className={`size-2.5 rounded-full ${meta.dot}`} aria-hidden />
      <span className="font-medium">{meta.label}</span>
      {!connection.agent_online && (
        <span className="text-xs font-semibold text-red-600">· agent offline</span>
      )}
      {connection.mock_mode && (
        <span className="rounded bg-amber-100 px-1.5 text-[10px] font-bold text-amber-900">MOCK</span>
      )}
    </div>
  );
}

/** Compact, always-visible status of the Cardmarket connection. */
export function ConnectionBanner() {
  const { data: connection } = useConnection();
  const { data: me } = useMe();
  if (!connection) return null;
  const bad = NEEDS_HUMAN.has(connection.status) || !connection.agent_online;
  const canFix = me?.permissions.includes("MANAGE_CONNECTION");
  return (
    <div
      data-testid="connection-banner"
      data-status={connection.status}
      className={`card mb-4 flex flex-wrap items-center justify-between gap-2 px-4 py-3 ${
        bad ? "border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950/60" : ""
      }`}
    >
      <div className="min-w-0">
        <ConnectionLine connection={connection} />
        <p className="mt-0.5 text-xs text-slate-500">
          {connection.status === "CONNECTED"
            ? `Ultima sincronizzazione: ${formatAgo(connection.last_successful_sync)}`
            : connection.last_error_code
              ? ERROR_CODE[connection.last_error_code]
              : !connection.agent_online
                ? "L'agent non risponde: verifica che il servizio sia avviato"
                : "Collega l'account Cardmarket per iniziare"}
        </p>
      </div>
      {bad && canFix && (
        <Link href="/settings/connection" className="btn-primary min-h-9 px-3 text-xs">
          {connection.status === "DISCONNECTED" ? "Collega" : "Riconnetti"}
        </Link>
      )}
    </div>
  );
}
