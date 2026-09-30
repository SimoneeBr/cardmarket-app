"use client";

import type {
  CartDetail,
  CartListItem,
  Connection,
  ConversationDetail,
  ConversationListItem,
  Dashboard,
  Me,
  Notification,
  OrderDetail,
  OrderListItem,
  Page,
  SetupStatus,
  Template,
} from "@cmc/types";
import {
  keepPreviousData,
  useInfiniteQuery,
  useQuery,
  type QueryClient,
} from "@tanstack/react-query";

import { api, ApiError } from "./api";

/** Polling intervals (ms). Realtime is polling-based in the MVP. */
export const POLL = {
  dashboard: 15_000,
  lists: 30_000,
  conversation: 5_000,
  pending: 2_000,
  notifications: 20_000,
  connection: 10_000,
} as const;

export const keys = {
  me: ["me"] as const,
  setup: ["setup"] as const,
  dashboard: ["dashboard"] as const,
  orders: (params: object) => ["orders", params] as const,
  order: (id: number) => ["order", id] as const,
  conversations: (params: object) => ["conversations", params] as const,
  conversation: (id: number) => ["conversation", id] as const,
  carts: (params: object) => ["carts", params] as const,
  cart: (id: number) => ["cart", id] as const,
  notifications: ["notifications"] as const,
  unread: ["notifications", "unread"] as const,
  templates: ["templates"] as const,
  connection: ["connection"] as const,
};

export function useMe() {
  return useQuery({
    queryKey: keys.me,
    queryFn: () => api.get<Me>("/me"),
    retry: (count, error) => !(error instanceof ApiError && error.status === 401) && count < 2,
    staleTime: 60_000,
  });
}

export function useSetupStatus() {
  return useQuery({ queryKey: keys.setup, queryFn: () => api.get<SetupStatus>("/setup/status") });
}

export function useDashboard() {
  return useQuery({
    queryKey: keys.dashboard,
    queryFn: () => api.get<Dashboard>("/dashboard"),
    refetchInterval: POLL.dashboard,
  });
}

const PAGE_SIZE = 30;

function infiniteList<T>(key: readonly unknown[], path: string, params: Record<string, string>) {
  return {
    queryKey: key,
    queryFn: ({ pageParam }: { pageParam: number }) =>
      api.get<Page<T>>(path, { ...params, limit: PAGE_SIZE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last: Page<T>) =>
      last.offset + last.items.length < last.total ? last.offset + last.items.length : undefined,
    refetchInterval: POLL.lists,
    placeholderData: keepPreviousData,
  };
}

export function useOrders(params: { filter: string; q: string; sort: string }) {
  return useInfiniteQuery(infiniteList<OrderListItem>(keys.orders(params), "/orders", params));
}

export function useOrder(id: number) {
  return useQuery({
    queryKey: keys.order(id),
    queryFn: () => api.get<OrderDetail>(`/orders/${id}`),
    refetchInterval: (query) => (query.state.data?.pending_action ? POLL.pending : POLL.lists),
  });
}

export function useConversations(params: { filter: string; q: string }) {
  return useInfiniteQuery(
    infiniteList<ConversationListItem>(keys.conversations(params), "/conversations", params),
  );
}

export function useConversation(id: number) {
  return useQuery({
    queryKey: keys.conversation(id),
    queryFn: () => api.get<ConversationDetail>(`/conversations/${id}`),
    refetchInterval: (query) =>
      query.state.data?.messages.some((m) => m.status === "PENDING")
        ? POLL.pending
        : POLL.conversation,
  });
}

export function useCarts(params: { filter: string; q: string }) {
  return useInfiniteQuery(infiniteList<CartListItem>(keys.carts(params), "/carts", params));
}

export function useCart(id: number) {
  return useQuery({ queryKey: keys.cart(id), queryFn: () => api.get<CartDetail>(`/carts/${id}`) });
}

export function useUnreadCount() {
  return useQuery({
    queryKey: keys.unread,
    queryFn: () => api.get<{ unread: number }>("/notifications/unread-count"),
    refetchInterval: POLL.notifications,
  });
}

export function useNotifications() {
  return useQuery({
    queryKey: keys.notifications,
    queryFn: () => api.get<Page<Notification>>("/notifications", { limit: 100 }),
    refetchInterval: POLL.notifications,
  });
}

export function useTemplates() {
  return useQuery({
    queryKey: keys.templates,
    queryFn: () => api.get<Template[]>("/templates"),
    staleTime: 5 * 60_000,
  });
}

export function useConnection(options: { fast?: boolean } = {}) {
  return useQuery({
    queryKey: keys.connection,
    queryFn: () => api.get<Connection>("/connection/status"),
    refetchInterval: (query) =>
      options.fast || query.state.data?.pending_session_action ? POLL.pending : POLL.connection,
  });
}

export function invalidateCommerce(client: QueryClient) {
  for (const key of ["dashboard", "orders", "order", "conversations", "conversation", "carts"]) {
    void client.invalidateQueries({ queryKey: [key] });
  }
}
