/**
 * Public API types for the web app, generated from the FastAPI OpenAPI schema.
 * Regenerate with `npm run gen:types` after changing API schemas.
 */
import type { components } from "./api";

type S = components["schemas"];

export type Me = S["MeOut"];
export type User = S["UserOut"];
export type SetupStatus = S["SetupStatus"];
export type Dashboard = S["DashboardOut"];
export type ActivityItem = S["ActivityItem"];

export type OrderListItem = S["OrderListItem"];
export type OrderDetail = S["OrderDetail"];
export type Item = S["ItemOut"];
export type OrderStatus = S["OrderStatus"];
export type PaymentStatus = S["PaymentStatus"];
export type ShippingStatus = S["ShippingStatus"];

export type ConversationListItem = S["ConversationListItem"];
export type ConversationDetail = S["ConversationDetail"];
export type Message = S["MessageOut"];
export type MessageStatus = S["MessageStatus"];

export type CartListItem = S["CartListItem"];
export type CartDetail = S["CartDetail"];
export type CartStatus = S["CartStatus"];

export type Notification = S["NotificationOut"];
export type NotificationType = S["NotificationType"];
export type NotificationPreference = S["NotificationPreferenceOut"];
export type PushConfig = S["PushConfigOut"];

export type Template = S["TemplateOut"];
export type TemplateInput = S["TemplateIn"];
export type TemplateRender = S["TemplateRenderOut"];

export type Connection = S["ConnectionOut"];
export type ConnectionStatus = S["ConnectionStatus"];
export type ActionBrief = S["ActionBrief"];
export type Action = S["ActionOut"];
export type ActionStatus = S["ActionStatus"];
export type SyncRun = S["SyncRunOut"];
export type SyncStatus = S["SyncStatusOut"];
export type AuditLog = S["AuditLogOut"];
export type RuntimeSettings = S["RuntimeSettingsOut"];
export type ErrorsReport = S["ErrorsOut"];
export type ErrorCode = S["ErrorCode"];
export type UserRole = S["UserRole"];

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
