const LOCALE = "it-IT";

export function formatMoney(amount: string | number | null | undefined, currency = "EUR"): string {
  if (amount === null || amount === undefined || amount === "") return "—";
  const value = typeof amount === "number" ? amount : Number(amount);
  if (Number.isNaN(value)) return "—";
  return new Intl.NumberFormat(LOCALE, { style: "currency", currency }).format(value);
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(LOCALE, {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit" }).format(
    new Date(iso),
  );
}

/** "ora", "2 min", "3 h", "ieri", "12/09" — compact, for lists. */
export function formatRelative(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "";
  const date = new Date(iso);
  const seconds = Math.round((now.getTime() - date.getTime()) / 1000);
  if (seconds < 45) return "ora";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  const sameDay = date.toDateString() === now.toDateString();
  if (sameDay || hours < 6) return `${hours} h`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "ieri";
  return new Intl.DateTimeFormat(LOCALE, { day: "2-digit", month: "2-digit" }).format(date);
}

/** "30 secondi fa", "5 minuti fa" — for status lines. */
export function formatAgo(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "mai";
  const seconds = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return `${seconds} secondi fa`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return minutes === 1 ? "1 minuto fa" : `${minutes} minuti fa`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return hours === 1 ? "1 ora fa" : `${hours} ore fa`;
  return formatDateTime(iso);
}
