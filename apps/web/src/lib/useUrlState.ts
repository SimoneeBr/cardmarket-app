"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

/** A query-string backed piece of state (keeps filters shareable/back-button friendly). */
export function useUrlState<T extends string>(key: string, fallback: T, allowed?: readonly T[]) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const raw = params.get(key) as T | null;
  const value = raw && (!allowed || allowed.includes(raw)) ? raw : fallback;
  const setValue = useCallback(
    (next: T) => {
      const copy = new URLSearchParams(params.toString());
      if (next === fallback || next === "") copy.delete(key);
      else copy.set(key, next);
      const qs = copy.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [params, router, pathname, key, fallback],
  );
  return [value, setValue] as const;
}
