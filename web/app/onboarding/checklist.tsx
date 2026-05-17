"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import type { IntegrationAccount, UserProfile } from "@/types";
import { getCachedIdToken } from "@/lib/session-token";

interface OnboardingChecklistProps {
  user: UserProfile | null;
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

type MarketplaceProvider = "fb" | "nextdoor" | "offerup" | "craigslist";

interface MarketplaceConfig {
  provider: MarketplaceProvider;
  label: string;
  sub: string;
  /** When true, the tile is disabled in the UI with a "Coming soon"
   * badge — the backend still supports the provider so the user can
   * enable it later if e.g. Browserbase Scale-tier features land. */
  comingSoon?: boolean;
  /** Why the provider is unavailable. Surfaces as the tile's subtitle
   * when ``comingSoon`` is true. */
  comingSoonReason?: string;
}

const MARKETPLACES: MarketplaceConfig[] = [
  {
    provider: "fb",
    label: "Facebook Marketplace",
    sub: "facebook.com/marketplace",
    comingSoon: true,
    comingSoonReason:
      "Meta's anti-bot blocks remote-browser sessions on the free tier — coming once we ship stealth proxies.",
  },
  { provider: "nextdoor", label: "Nextdoor", sub: "nextdoor.com" },
  { provider: "offerup", label: "OfferUp", sub: "offerup.com" },
  { provider: "craigslist", label: "Craigslist", sub: "craigslist.org" },
];

// Per-tile state. `idle` = no action in flight, `opening` = /link
// request in flight, `tab_open` = the Live View tab has been opened
// and we're awaiting the user clicking "I'm done", `finishing` = the
// /finish call is in flight.
type TileStage = "idle" | "opening" | "tab_open" | "finishing";

async function fetchWithAuth<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  // Pull the Google ID token from the shared client-side cache. Each
  // `fetchWithAuth` would otherwise hit `/api/auth/session` on every call.
  const idToken = await getCachedIdToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) ?? {}),
  };
  if (idToken) {
    headers["Authorization"] = `Bearer ${idToken}`;
  }
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
  if (!res.ok) {
    // Surface the backend's ``detail`` field so the user sees the real
    // exception (e.g. "Browserbase quota exceeded", "context create
    // failed: ...") instead of a bare HTTP status code.
    let detail = "";
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body?.detail === "string") detail = ` — ${body.detail}`;
    } catch {
      /* response wasn't JSON; fall back to status only */
    }
    const err = new Error(
      `${init?.method ?? "GET"} ${path} failed: ${res.status}${detail}`,
    ) as Error & { status?: number; errorCode?: string };
    err.status = res.status;
    err.errorCode = res.headers.get("x-goti-error-code") ?? undefined;
    throw err;
  }
  return (await res.json()) as T;
}

export function OnboardingChecklist({ user }: OnboardingChecklistProps) {
  const router = useRouter();
  const [profile, setProfile] = useState<UserProfile | null>(user);
  const [locationInput, setLocationInput] = useState<string>(
    user?.location ?? ""
  );
  const [savingLocation, setSavingLocation] = useState(false);
  const [completing, startCompleting] = useTransition();

  // Per-provider state machine. Multiple tiles can be in flight at
  // once (e.g. user opened FB tab, then opened Nextdoor tab in parallel).
  const [tileStage, setTileStage] = useState<
    Record<MarketplaceProvider, TileStage>
  >({ fb: "idle", nextdoor: "idle", offerup: "idle", craigslist: "idle" });
  const [linkError, setLinkError] = useState<string | null>(null);
  // When Browserbase returns 402 Payment Required (free-tier monthly
  // minutes exhausted), every link / discovery / negotiation call
  // fails the same way until the user upgrades. We special-case it
  // with a dedicated banner so the user knows the fix is at
  // browserbase.com/plans, not a Goti bug.
  const [quotaExhausted, setQuotaExhausted] = useState(false);
  // Per-tile error surfaced when /finish reports the marketplace
  // bounced the validation roundtrip back to a login page (i.e. the
  // user's sign-in didn't actually take).
  const [tileError, setTileError] = useState<
    Record<MarketplaceProvider, string | null>
  >({ fb: null, nextdoor: null, offerup: null, craigslist: null });

  // Re-poll when the user comes back from the link tab so the linked
  // state propagates without a manual refresh.
  useEffect(() => {
    function onVisibility() {
      if (document.visibilityState === "visible") {
        fetchWithAuth<UserProfile>("/api/me")
          .then((p) => setProfile(p))
          .catch(() => {
            /* ignore — stale state is fine */
          });
      }
    }
    document.addEventListener("visibilitychange", onVisibility);
    return () =>
      document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  // Per-provider linked map keyed by provider, derived from the
  // profile.integrations array (always returns one entry per provider,
  // even if not linked).
  const linkedByProvider = useMemo(() => {
    const out: Record<MarketplaceProvider, IntegrationAccount | null> = {
      fb: null,
      nextdoor: null,
      offerup: null,
      craigslist: null,
    };
    for (const i of profile?.integrations ?? []) {
      if (i.provider in out) {
        out[i.provider as MarketplaceProvider] = i;
      }
    }
    return out;
  }, [profile]);

  // The user can move on once at least ONE marketplace is linked
  // (active). They can come back to /account to link the rest later.
  const anyMarketplaceLinked = useMemo(
    () => (profile?.integrations ?? []).some((i) => i.linked),
    [profile]
  );
  const locationSet = Boolean(profile?.location);
  const canStart = anyMarketplaceLinked;

  // Progress: 3 steps total (signed-in always counts; at-least-one
  // marketplace; optional location).
  const stepsComplete = [true, anyMarketplaceLinked, locationSet].filter(
    Boolean
  ).length;
  const totalSteps = 3;
  const progressPct = Math.round((stepsComplete / totalSteps) * 100);

  if (!profile) {
    return (
      <p className="text-graphite">
        Couldn’t reach the Goti backend. Try refreshing — if it keeps
        failing, something is wrong with the API.
      </p>
    );
  }

  async function startLink(provider: MarketplaceProvider) {
    setLinkError(null);
    setTileStage((s) => ({ ...s, [provider]: "opening" }));
    try {
      const resp = await fetchWithAuth<{
        authorize_url: string;
        state: string;
      }>(`/api/integrations/${provider}/link`, {
        method: "POST",
        body: "{}",
      });
      if (resp.authorize_url) {
        window.open(resp.authorize_url, "_blank", "noopener,noreferrer");
        setTileStage((s) => ({ ...s, [provider]: "tab_open" }));
      } else {
        setLinkError("Backend didn't return a login URL.");
        setTileStage((s) => ({ ...s, [provider]: "idle" }));
      }
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("link init failed", err);
      const e = err as Error & { status?: number; errorCode?: string };
      if (e?.status === 402 || e?.errorCode === "browserbase_quota_exhausted") {
        setQuotaExhausted(true);
      } else {
        setLinkError(
          err instanceof Error
            ? `Couldn't start the link: ${err.message}`
            : "Couldn't start the link."
        );
      }
      setTileStage((s) => ({ ...s, [provider]: "idle" }));
    }
  }

  async function finishLinkFor(provider: MarketplaceProvider) {
    setLinkError(null);
    setTileError((s) => ({ ...s, [provider]: null }));
    setTileStage((s) => ({ ...s, [provider]: "finishing" }));
    try {
      // Backend now returns ``{ok, validated, error?}`` — when
      // ``validated`` is false the marketplace bounced the validation
      // probe to a login page, so we keep the tile in tab_open + show
      // the error inline.
      const resp = await fetchWithAuth<{
        ok: boolean;
        validated: boolean;
        error?: string;
      }>(`/api/integrations/${provider}/finish`, {
        method: "POST",
        body: "{}",
      });
      if (resp.validated === false) {
        setTileError((s) => ({
          ...s,
          [provider]: resp.error ?? "Login didn't take — try again.",
        }));
        setTileStage((s) => ({ ...s, [provider]: "tab_open" }));
        return;
      }
      // Refresh the profile so the checklist reflects the linked state.
      const refreshed = await fetchWithAuth<UserProfile>("/api/me");
      setProfile(refreshed);
      setTileStage((s) => ({ ...s, [provider]: "idle" }));
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("link finish failed", err);
      setLinkError(
        err instanceof Error
          ? `Couldn't finish the link: ${err.message}`
          : "Couldn't finish the link."
      );
      // Keep the user in tab_open so they can retry "I'm done".
      setTileStage((s) => ({ ...s, [provider]: "tab_open" }));
    }
  }

  async function saveLocation() {
    if (!locationInput.trim()) return;
    setSavingLocation(true);
    try {
      await fetchWithAuth<{ ok: true; location: string }>(
        "/api/me/location",
        {
          method: "PATCH",
          body: JSON.stringify({ location: locationInput.trim() }),
        }
      );
      setProfile((prev) =>
        prev ? { ...prev, location: locationInput.trim() } : prev
      );
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("location save failed", err);
    } finally {
      setSavingLocation(false);
    }
  }

  function finishOnboarding() {
    startCompleting(async () => {
      try {
        await fetchWithAuth("/api/me/onboarding/complete", {
          method: "POST",
          body: "{}",
        });
      } finally {
        router.push("/");
      }
    });
  }

  return (
    <div className="flex flex-col gap-6">
      {quotaExhausted ? (
        <div
          role="alert"
          className="flex flex-col gap-2 rounded-2xl border border-orange/40 bg-orange/10 px-5 py-4"
        >
          <div className="text-base font-semibold text-ink">
            Browserbase quota exhausted
          </div>
          <p className="text-sm text-ink-2 leading-relaxed">
            Goti drives a real headless browser for every marketplace
            action. Your Browserbase free-tier monthly minutes are
            spent, so no new browser sessions can start until you
            upgrade your plan (or wait for the monthly reset). This is
            a Browserbase tier limit, not a Goti bug.
          </p>
          <div className="flex items-center gap-3 pt-1">
            <a
              href="https://browserbase.com/plans"
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-1 rounded-lg bg-orange px-3 py-1.5 text-sm font-semibold text-paper border border-ink-line hover:bg-orange/95 transition"
            >
              Upgrade Browserbase →
            </a>
            <button
              type="button"
              onClick={() => setQuotaExhausted(false)}
              className="text-sm text-ink-3 hover:text-ink underline-offset-2 hover:underline"
            >
              Dismiss
            </button>
          </div>
        </div>
      ) : null}

      {linkError ? (
        <div
          role="status"
          aria-live="polite"
          className="flex items-start justify-between gap-3 rounded-xl border border-accent/30 bg-paper-2 px-4 py-3 text-sm text-ink"
        >
          <span>{linkError}</span>
          <button
            type="button"
            aria-label="Dismiss"
            onClick={() => setLinkError(null)}
            className="shrink-0 text-ink-3 hover:text-ink"
          >
            ×
          </button>
        </div>
      ) : null}

      {/* Progress bar */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between text-xs text-ink-3">
          <span>
            Step {Math.min(stepsComplete + (canStart ? 0 : 1), totalSteps)} of{" "}
            {totalSteps}
          </span>
          <span>{progressPct}% complete</span>
        </div>
        <div className="h-2 w-full rounded-full bg-paper-2 overflow-hidden">
          <div
            className="h-full bg-ink transition-all duration-500"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      <ul className="flex flex-col gap-3">
        {/* Step 1 — Signed in */}
        <ChecklistRow
          n={1}
          done
          title={`Signed in as ${profile.name ?? profile.email}`}
          subtitle={profile.email}
        />

        {/* Step 2 — Link marketplaces. Four per-marketplace tiles. */}
        <li
          className={`flex flex-col gap-4 p-4 rounded-2xl border transition ${
            anyMarketplaceLinked
              ? "bg-green-soft/40 border-green/20"
              : "bg-paper-2 border-ink-3/10"
          }`}
        >
          <div className="flex items-start gap-4">
            <span
              className={`mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-medium ${
                anyMarketplaceLinked
                  ? "bg-green text-paper"
                  : "bg-paper border border-ink-3/30 text-ink-3"
              }`}
              aria-hidden="true"
            >
              {anyMarketplaceLinked ? "✓" : 2}
            </span>
            <div className="flex-1 min-w-0">
              <div
                className="font-medium text-ink"
                style={{ fontSize: "var(--text-subhead)" }}
              >
                Link your marketplaces
              </div>
              <div className="text-sm text-ink-2 leading-relaxed">
                Click a tile to open a remote browser tab on that marketplace.
                Sign in there, then come back and click “I’m done.” Link at
                least one to continue — you can add the others later.
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {MARKETPLACES.map((m) => (
              <MarketplaceTile
                key={m.provider}
                provider={m.provider}
                label={m.label}
                sub={m.sub}
                comingSoon={Boolean(m.comingSoon)}
                comingSoonReason={m.comingSoonReason}
                stage={tileStage[m.provider]}
                linked={Boolean(linkedByProvider[m.provider]?.linked)}
                error={tileError[m.provider]}
                onLink={() => startLink(m.provider)}
                onFinish={() => finishLinkFor(m.provider)}
              />
            ))}
          </div>
        </li>

        {/* Step 3 — Optional default location */}
        <ChecklistRow
          n={3}
          done={locationSet}
          optional
          skippable={!locationSet}
          title={
            profile.location
              ? `Default location: ${profile.location}`
              : "Set your default location"
          }
          subtitle="We use this to filter listings by proximity."
          action={
            !locationSet ? (
              <div className="flex gap-2">
                <input
                  type="text"
                  value={locationInput}
                  onChange={(e) => setLocationInput(e.target.value)}
                  placeholder="e.g. San Francisco"
                  className="px-3 py-1.5 rounded-lg border border-ink-3/30 bg-paper text-sm w-44 focus:outline-none focus:ring-2 focus:ring-orange/40"
                />
                <button
                  type="button"
                  onClick={saveLocation}
                  disabled={savingLocation || !locationInput.trim()}
                  className="px-3 py-1.5 rounded-lg bg-paper text-ink text-sm border border-ink-3/30 hover:bg-paper-3 disabled:opacity-50 transition"
                >
                  Save
                </button>
              </div>
            ) : (
              <span className="text-xs text-green font-medium">Saved</span>
            )
          }
        />
      </ul>

      <div className="pt-2">
        <button
          type="button"
          onClick={finishOnboarding}
          disabled={!canStart || completing}
          className="w-full py-3 px-4 rounded-xl bg-ink text-paper font-medium hover:bg-ink-2 transition disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {canStart
            ? completing
              ? "Starting…"
              : "Continue to your first hunt"
            : "Link at least one marketplace to continue"}
        </button>
        {canStart ? (
          <p className="mt-3 text-center text-xs text-ink-3">
            You can manage your account, relink, or delete it at any time
            in{" "}
            <a
              href="/account"
              className="underline hover:text-ink-2"
            >
              Account
            </a>
            .
          </p>
        ) : null}
      </div>
    </div>
  );
}

interface MarketplaceTileProps {
  provider: MarketplaceProvider;
  label: string;
  sub: string;
  comingSoon: boolean;
  comingSoonReason?: string;
  stage: TileStage;
  linked: boolean;
  error: string | null;
  onLink: () => void;
  onFinish: () => void;
}

function MarketplaceTile({
  label,
  sub,
  comingSoon,
  comingSoonReason,
  stage,
  linked,
  error,
  onLink,
  onFinish,
}: MarketplaceTileProps) {
  if (comingSoon) {
    return (
      <div
        className="rounded-xl border p-4 flex flex-col gap-3 bg-paper-2/60 border-ink-3/10 opacity-70"
        aria-disabled="true"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="font-medium text-ink-2 truncate">{label}</div>
            <div className="text-xs text-ink-3 truncate">{sub}</div>
          </div>
          <span className="inline-flex items-center rounded-full bg-paper-3 px-2 py-0.5 text-xs font-medium text-ink-3">
            Coming soon
          </span>
        </div>
        {comingSoonReason ? (
          <p className="text-xs text-ink-3 leading-relaxed">{comingSoonReason}</p>
        ) : null}
        <button
          type="button"
          disabled
          className="w-full px-3 py-1.5 rounded-lg bg-paper text-ink-3 text-sm border border-ink-3/20 cursor-not-allowed"
        >
          Link
        </button>
      </div>
    );
  }

  return (
    <div
      className={`rounded-xl border p-4 flex flex-col gap-3 transition ${
        linked
          ? "bg-white border-green/30"
          : "bg-white border-ink-3/15"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="font-medium text-ink truncate">{label}</div>
          <div className="text-xs text-ink-3 truncate">{sub}</div>
        </div>
        {linked ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-green/15 px-2 py-0.5 text-xs font-medium text-green">
            <span aria-hidden>✓</span> Linked
          </span>
        ) : (
          <span className="inline-flex items-center rounded-full bg-paper-2 px-2 py-0.5 text-xs font-medium text-ink-3">
            Not linked
          </span>
        )}
      </div>
      {error ? (
        <p className="text-xs text-orange leading-relaxed">{error}</p>
      ) : null}
      <div>
        {linked ? (
          <button
            type="button"
            onClick={onLink}
            disabled={stage !== "idle"}
            className="w-full px-3 py-1.5 rounded-lg bg-paper text-ink text-sm border border-ink-3/30 hover:bg-paper-3 transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {stage === "opening" ? "Opening…" : "Relink"}
          </button>
        ) : stage === "tab_open" || stage === "finishing" ? (
          <button
            type="button"
            onClick={onFinish}
            disabled={stage === "finishing"}
            className="w-full px-3 py-1.5 rounded-lg bg-ink text-paper text-sm hover:bg-ink-2 transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {stage === "finishing"
              ? "Finishing…"
              : `I’m done logging in with ${label}`}
          </button>
        ) : (
          <button
            type="button"
            onClick={onLink}
            disabled={stage === "opening"}
            className="w-full px-3 py-1.5 rounded-lg bg-ink text-paper text-sm hover:bg-ink-2 transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {stage === "opening" ? "Opening…" : "Link"}
          </button>
        )}
      </div>
    </div>
  );
}

interface RowProps {
  n: number;
  done?: boolean;
  optional?: boolean;
  skippable?: boolean;
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}

function ChecklistRow({
  n,
  done,
  optional,
  title,
  subtitle,
  action,
}: RowProps) {
  return (
    <li
      className={`flex items-start gap-4 p-4 rounded-2xl border transition ${
        done
          ? "bg-green-soft/40 border-green/20"
          : "bg-paper-2 border-ink-3/10"
      }`}
    >
      <span
        className={`mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-medium ${
          done
            ? "bg-green text-paper"
            : "bg-paper border border-ink-3/30 text-ink-3"
        }`}
        aria-hidden="true"
      >
        {done ? "✓" : n}
      </span>
      <div className="flex-1 min-w-0">
        <div
          className="font-medium text-ink"
          style={{ fontSize: "var(--text-subhead)" }}
        >
          {title}
          {optional && (
            <span className="ml-2 text-xs text-ink-3 font-normal">
              optional
            </span>
          )}
        </div>
        {subtitle && (
          <div className="text-sm text-ink-2 leading-relaxed">{subtitle}</div>
        )}
      </div>
      {action && <div className="shrink-0 self-center">{action}</div>}
    </li>
  );
}
