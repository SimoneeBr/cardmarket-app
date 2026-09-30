"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { AppShell } from "@/components/AppShell";
import { Spinner } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useMe, useSetupStatus } from "@/lib/queries";

export default function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const me = useMe();
  const setup = useSetupStatus();

  useEffect(() => {
    if (setup.data?.needs_admin) router.replace("/setup");
    else if (me.error instanceof ApiError && me.error.status === 401) {
      router.replace(`/login?next=${encodeURIComponent(window.location.pathname)}`);
    }
  }, [me.error, setup.data, router]);

  if (!me.data) return <Spinner />;
  return <AppShell>{children}</AppShell>;
}
