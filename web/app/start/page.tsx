import { Suspense } from "react";

import { MarketplacesStrip9 } from "@/components/marketplace/marketplaces-strip-9";
import { HuntSidebar } from "@/components/sidebar/hunt-sidebar";
import { NLInputHero } from "@/components/start/nl-input-hero";
import { ActivityBell } from "@/components/topnav/activity-bell";
import { GotiMark } from "@/components/topnav/goti-mark";

export default function StartPage() {
  return (
    <div className="min-h-screen bg-paper text-ink flex">
      <Suspense fallback={null}>
        <HuntSidebar />
      </Suspense>
      <main className="flex-1 min-w-0 flex flex-col">
        <header className="mx-auto flex w-full max-w-[1200px] items-center justify-between px-6 py-5 lg:justify-end">
          <GotiMark showSubtitle={false} className="lg:hidden" />
          <ActivityBell />
        </header>

        <section className="flex-1 mx-auto flex w-full max-w-[1200px] flex-col items-center justify-center px-6 pt-12 pb-16">
          <NLInputHero />
        </section>

        <section
          className="mx-auto w-full max-w-[1200px] border-t px-6 py-8"
          style={{ borderColor: "rgba(15,15,15,0.08)" }}
        >
          <MarketplacesStrip9 />
        </section>

        <footer className="mx-auto w-full max-w-[1200px] px-6 py-6 text-micro text-ink-3 flex items-center justify-between">
          <span>Goti · Buyer agent for used marketplaces</span>
          <span>Nothing sent yet.</span>
        </footer>
      </main>
    </div>
  );
}
