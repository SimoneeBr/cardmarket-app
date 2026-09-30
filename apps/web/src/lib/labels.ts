import type {
  ActionStatus,
  CartStatus,
  ConnectionStatus,
  ErrorCode,
  MessageStatus,
  NotificationType,
  OrderStatus,
  UserRole,
} from "@cmc/types";

export type Tone = "neutral" | "info" | "success" | "warning" | "danger" | "accent";

export const ORDER_STATUS: Record<OrderStatus, { label: string; tone: Tone }> = {
  UNPAID: { label: "Non pagato", tone: "warning" },
  PAID: { label: "Da spedire", tone: "accent" },
  SHIPPED: { label: "Spedito", tone: "info" },
  COMPLETED: { label: "Completato", tone: "success" },
  CANCELLED: { label: "Annullato", tone: "neutral" },
  UNKNOWN: { label: "Sconosciuto", tone: "neutral" },
};

export const CART_STATUS: Record<CartStatus, { label: string; tone: Tone }> = {
  TO_PAY: { label: "Da pagare", tone: "warning" },
  PAID: { label: "Pagato", tone: "accent" },
  COMPLETED: { label: "Completato", tone: "success" },
  CANCELLED: { label: "Annullato", tone: "neutral" },
  UNKNOWN: { label: "Sconosciuto", tone: "neutral" },
};

export const MESSAGE_STATUS: Record<MessageStatus, { label: string; tone: Tone }> = {
  PENDING: { label: "In invio…", tone: "neutral" },
  SENT: { label: "Inviato", tone: "success" },
  FAILED: { label: "Non inviato", tone: "danger" },
  UNKNOWN: { label: "Esito da verificare", tone: "warning" },
};

export const ACTION_STATUS: Record<ActionStatus, { label: string; tone: Tone }> = {
  PENDING: { label: "In coda", tone: "neutral" },
  PROCESSING: { label: "In esecuzione", tone: "info" },
  SUCCESS: { label: "Riuscita", tone: "success" },
  FAILED: { label: "Fallita", tone: "danger" },
  NEEDS_ATTENTION: { label: "Da verificare", tone: "warning" },
};

export const CONNECTION_STATUS: Record<
  ConnectionStatus,
  { label: string; tone: Tone; dot: string }
> = {
  CONNECTED: { label: "Cardmarket connesso", tone: "success", dot: "bg-emerald-500" },
  CONNECTING: { label: "Connessione in corso…", tone: "info", dot: "bg-sky-500 animate-pulse" },
  DISCONNECTED: { label: "Cardmarket disconnesso", tone: "neutral", dot: "bg-slate-400" },
  AUTH_REQUIRED: { label: "Autenticazione Cardmarket richiesta", tone: "danger", dot: "bg-red-500" },
  SESSION_EXPIRED: { label: "Sessione Cardmarket scaduta", tone: "danger", dot: "bg-red-500" },
  ERROR: { label: "Errore connessione Cardmarket", tone: "danger", dot: "bg-red-500" },
};

export const ERROR_CODE: Record<ErrorCode, string> = {
  AUTH_ERROR: "Autenticazione Cardmarket non valida",
  NETWORK_ERROR: "Rete / Cardmarket non raggiungibile",
  CARDMARKET_CHANGED: "Pagina Cardmarket non riconosciuta (sito cambiato?)",
  ACCESS_BLOCKED: "Accesso bloccato dal firewall (Cloudflare) prima di raggiungere Cardmarket",
  SELECTOR_NOT_FOUND: "Elemento della pagina non trovato o ambiguo",
  TIMEOUT: "Timeout",
  ACTION_FAILED: "Azione non riuscita",
  VERIFICATION_FAILED: "Esito non verificabile",
  DATABASE_ERROR: "Errore database",
  UNKNOWN: "Errore sconosciuto",
};

export const NOTIFICATION_TYPE: Record<NotificationType, { label: string; icon: string }> = {
  ORDER_CREATED: { label: "Nuovo ordine", icon: "📦" },
  ORDER_PAID: { label: "Ordine pagato", icon: "💶" },
  ORDER_SHIPPED: { label: "Ordine spedito", icon: "🚚" },
  MESSAGE_RECEIVED: { label: "Nuovo messaggio", icon: "💬" },
  CART_CREATED: { label: "Nuovo carrello", icon: "🛒" },
  CART_PAID: { label: "Carrello pagato", icon: "✅" },
  SESSION_EXPIRED: { label: "Sessione Cardmarket scaduta", icon: "🔐" },
  SYNC_ERROR: { label: "Errore di sincronizzazione", icon: "⚠️" },
  ACTION_FAILED: { label: "Azione non riuscita", icon: "❗" },
};

export const ROLE: Record<UserRole, string> = {
  ADMIN: "Amministratore",
  MANAGER: "Manager",
  STAFF: "Staff",
};

export const TONE_CLASSES: Record<Tone, string> = {
  neutral: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  info: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  success: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  warning: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
  danger: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  accent: "bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300",
};
