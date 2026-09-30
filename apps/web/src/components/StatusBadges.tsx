import type { ActionStatus, CartStatus, MessageStatus, OrderStatus } from "@cmc/types";

import { ACTION_STATUS, CART_STATUS, MESSAGE_STATUS, ORDER_STATUS } from "@/lib/labels";

import { Badge } from "./ui";

export function OrderStatusBadge({ status }: { status: OrderStatus }) {
  const s = ORDER_STATUS[status];
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

export function CartStatusBadge({ status }: { status: CartStatus }) {
  const s = CART_STATUS[status];
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

export function MessageStatusBadge({ status }: { status: MessageStatus }) {
  const s = MESSAGE_STATUS[status];
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

export function ActionStatusBadge({ status }: { status: ActionStatus }) {
  const s = ACTION_STATUS[status];
  return <Badge tone={s.tone}>{s.label}</Badge>;
}
