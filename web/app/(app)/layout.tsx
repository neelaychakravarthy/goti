import { Suspense } from "react";

import { OutboxBar } from "@/components/outbox/outbox-bar";
import { HuntSidebar } from "@/components/sidebar/hunt-sidebar";
import { TopNav } from "@/components/topnav/topnav";
import outbox from "@/mocks/outbox.json";
import type { Outbox } from "@/types";

export default function AppShellLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-paper text-ink flex">
      <Suspense fallback={null}>
        <HuntSidebar />
      </Suspense>
      <div className="flex-1 min-w-0 flex flex-col">
        <Suspense fallback={null}>
          <TopNav />
        </Suspense>
        <OutboxBar outbox={outbox as Outbox} />
        <main className="flex-1 min-w-0">{children}</main>
      </div>
    </div>
  );
}
