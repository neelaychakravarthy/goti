// Chat-app shell layout (sidebar + main slot).
//
// This is the SINGLE shell that wraps every authenticated, in-app
// route — root `/`, `/c/<hunt_id>`, `/memory`, `/memory/cases/<id>`.
// The old per-page chrome (TopNav with 5 step pills, HuntStatusBar,
// OutboxBar, MarketplacesStrip9) is gone. The sidebar carries
// everything navigational: hunts list, Inbox, "+ New hunt", Memory link.
//
// Auth check is server-side here so we redirect to /login BEFORE
// rendering any UI for unauthenticated users.

import { redirect } from "next/navigation";
import { Suspense } from "react";

import { auth } from "@/auth";
import { NotificationToast } from "@/components/notifications/notification-toast";
import { HuntSidebar } from "@/components/sidebar/hunt-sidebar";
import { NotificationsProvider } from "@/lib/notifications-context";

export default async function AppShellLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await auth();
  if (!session) {
    redirect("/login");
  }
  return (
    <NotificationsProvider>
      <div className="h-screen overflow-hidden bg-paper text-ink flex">
        <Suspense fallback={null}>
          <HuntSidebar />
        </Suspense>
        <main className="flex-1 min-w-0 flex flex-col overflow-hidden">
          {children}
        </main>
        <NotificationToast />
      </div>
    </NotificationsProvider>
  );
}
