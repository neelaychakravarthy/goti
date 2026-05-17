"use client";

// Interactive bits for the /account page. Server component
// (page.tsx) pre-fetches the profile + hands it in as `user`; this
// component owns the editable surface:
//
// - Profile card: avatar, name, email, member-since, location edit.
// - Linked accounts card: per-marketplace tiles (FB / Nextdoor /
//   OfferUp / Craigslist) — Link / Relink / Unlink.
// - Account actions: Sign out, Re-run onboarding, Delete account.
//
// The Delete-account button opens a confirmation modal that requires
// typing "DELETE" before the destructive button enables. On confirm,
// we DELETE /api/me then sign-out the NextAuth session and redirect
// to /login.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { signOut } from "next-auth/react";
import { useMemo, useState, useTransition } from "react";

import { ErrorMessage } from "@/components/ui/error-message";
import {
  deleteAccount,
  finishLink,
  linkIntegration,
  resetOnboarding,
  unlinkIntegration,
  updateLocation,
} from "@/lib/api-client";
import { clearCachedIdToken } from "@/lib/session-token";
import type { IntegrationAccount, UserProfile } from "@/types";

interface AccountViewProps {
  user: UserProfile;
}

type MarketplaceProvider = "fb" | "nextdoor" | "offerup" | "craigslist";

interface MarketplaceConfig {
  provider: MarketplaceProvider;
  label: string;
  sub: string;
  comingSoon?: boolean;
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

type TileStage = "idle" | "opening" | "tab_open" | "finishing" | "unlinking";

function formatMemberSince(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, {
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

export function AccountView({ user }: AccountViewProps) {
  const router = useRouter();
  const [profile, setProfile] = useState<UserProfile>(user);
  const [locationInput, setLocationInput] = useState<string>(
    user.location ?? ""
  );
  const [savingLocation, setSavingLocation] = useState(false);
  const [locationSaved, setLocationSaved] = useState(false);

  const [resetting, startResetting] = useTransition();
  const [resetMessage, setResetMessage] = useState<string | null>(null);

  // Per-provider state machine. Multiple tiles can be mid-flight at once.
  const [tileStage, setTileStage] = useState<
    Record<MarketplaceProvider, TileStage>
  >({ fb: "idle", nextdoor: "idle", offerup: "idle", craigslist: "idle" });
  const [linkError, setLinkError] = useState<string | null>(null);

  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Per-provider linked map keyed by provider, derived from the
  // profile.integrations array (always 4 entries).
  const linkedByProvider = useMemo(() => {
    const out: Record<MarketplaceProvider, IntegrationAccount | null> = {
      fb: null,
      nextdoor: null,
      offerup: null,
      craigslist: null,
    };
    for (const i of profile.integrations) {
      if (i.provider in out) {
        out[i.provider as MarketplaceProvider] = i;
      }
    }
    return out;
  }, [profile]);

  async function saveLocation() {
    if (!locationInput.trim()) return;
    setSavingLocation(true);
    setLocationSaved(false);
    try {
      await updateLocation(locationInput.trim());
      setProfile((p) => ({ ...p, location: locationInput.trim() }));
      setLocationSaved(true);
    } catch (err) {
      console.error("location save failed", err);
    } finally {
      setSavingLocation(false);
    }
  }

  async function handleLink(provider: MarketplaceProvider) {
    setLinkError(null);
    setTileStage((s) => ({ ...s, [provider]: "opening" }));
    try {
      const resp = await linkIntegration(provider);
      if (resp.authorize_url) {
        window.open(resp.authorize_url, "_blank", "noopener,noreferrer");
        setTileStage((s) => ({ ...s, [provider]: "tab_open" }));
      } else {
        setLinkError("Backend didn't return a login URL.");
        setTileStage((s) => ({ ...s, [provider]: "idle" }));
      }
    } catch (err) {
      console.error("link failed", err);
      setLinkError(
        err instanceof Error
          ? `Couldn't start the link: ${err.message}`
          : "Couldn't start the link."
      );
      setTileStage((s) => ({ ...s, [provider]: "idle" }));
    }
  }

  async function handleFinishLink(provider: MarketplaceProvider) {
    setLinkError(null);
    setTileStage((s) => ({ ...s, [provider]: "finishing" }));
    try {
      const resp = await finishLink(provider);
      // Backend ``/finish`` now runs a login-validation roundtrip
      // before flipping the row to linked. When it bounced to a login
      // page we keep the tile in tab_open and surface the message.
      if (resp.validated === false) {
        setLinkError(
          resp.error ??
            "Login didn't take — re-open the tab and complete sign-in.",
        );
        setTileStage((s) => ({ ...s, [provider]: "tab_open" }));
        return;
      }
      // Mark the row linked locally so the UI flips immediately. Any
      // already-linked providers are preserved.
      const nowIso = new Date().toISOString();
      setProfile((p) => ({
        ...p,
        marketplaces_status: "linked",
        integrations: p.integrations.map((i) =>
          i.provider === provider
            ? { ...i, linked: true, linked_at: nowIso, live_view_url: null }
            : i
        ),
      }));
      setTileStage((s) => ({ ...s, [provider]: "idle" }));
    } catch (err) {
      console.error("finish failed", err);
      setLinkError(
        err instanceof Error
          ? `Couldn't finish the link: ${err.message}`
          : "Couldn't finish the link."
      );
      // Keep the tile in tab_open so the user can retry.
      setTileStage((s) => ({ ...s, [provider]: "tab_open" }));
    }
  }

  async function handleUnlink(provider: MarketplaceProvider, label: string) {
    if (
      !window.confirm(
        `Unlink ${label}? You'll need to log in again to send messages there.`
      )
    ) {
      return;
    }
    setLinkError(null);
    setTileStage((s) => ({ ...s, [provider]: "unlinking" }));
    try {
      await unlinkIntegration(provider);
      setProfile((p) => {
        const integrations = p.integrations.map((i) =>
          i.provider === provider
            ? { ...i, linked: false, linked_at: null, live_view_url: null }
            : i
        );
        const anyStillLinked = integrations.some((i) => i.linked);
        return {
          ...p,
          marketplaces_status: anyStillLinked ? "linked" : "not linked",
          integrations,
        };
      });
      setTileStage((s) => ({ ...s, [provider]: "idle" }));
    } catch (err) {
      console.error("unlink failed", err);
      setLinkError(
        err instanceof Error
          ? `Couldn't unlink: ${err.message}`
          : "Couldn't unlink."
      );
      setTileStage((s) => ({ ...s, [provider]: "idle" }));
    }
  }

  function handleResetOnboarding() {
    setResetMessage(null);
    startResetting(async () => {
      try {
        await resetOnboarding();
        setResetMessage(
          "Onboarding reset. Redirecting…"
        );
        // Small delay so the user sees the toast before the redirect.
        setTimeout(() => router.push("/onboarding"), 500);
      } catch (err) {
        console.error("onboarding reset failed", err);
        setResetMessage("Couldn't reset onboarding. Try again.");
      }
    });
  }

  async function confirmDelete() {
    if (deleteConfirmText !== "DELETE") return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteAccount();
      // Drop the cached id token so the post-signOut redirect doesn't
      // race against a 401 from a stale token.
      clearCachedIdToken();
      await signOut({ callbackUrl: "/login" });
    } catch (err) {
      setDeleting(false);
      setDeleteError(
        err instanceof Error
          ? `Couldn't delete account: ${err.message}`
          : "Couldn't delete account."
      );
    }
  }

  const name = profile.name ?? profile.email;
  const initial = (name?.[0] ?? "?").toUpperCase();

  return (
    <div className="flex flex-col gap-6">
      {/* Back link */}
      <div>
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-sm text-ink-2 hover:text-ink transition"
        >
          <span aria-hidden>{"←"}</span>
          <span>Back to home</span>
        </Link>
      </div>

      <h1 className="font-display text-3xl text-ink">Account</h1>

      {/* Profile card */}
      <section className="rounded-3xl bg-white shadow-paper px-6 py-6 flex flex-col gap-4">
        <div className="flex items-start gap-4">
          {profile.picture ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={profile.picture}
              alt={name ?? "Avatar"}
              className="h-14 w-14 rounded-full"
              referrerPolicy="no-referrer"
            />
          ) : (
            <span className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-ink-3/20 text-xl font-medium">
              {initial}
            </span>
          )}
          <div className="flex-1 min-w-0">
            <div className="font-display text-xl text-ink truncate">{name}</div>
            <div className="text-sm text-ink-2 truncate">{profile.email}</div>
            <div className="text-xs text-ink-3 mt-1">
              Member since {formatMemberSince(profile.member_since)}
            </div>
          </div>
        </div>

        <div className="border-t border-ink-3/10 pt-4">
          <label
            htmlFor="acct-location"
            className="block text-sm font-medium text-ink mb-1"
          >
            Location
          </label>
          <div className="flex gap-2">
            <input
              id="acct-location"
              type="text"
              value={locationInput}
              onChange={(e) => {
                setLocationInput(e.target.value);
                setLocationSaved(false);
              }}
              placeholder="e.g. San Francisco"
              className="flex-1 px-3 py-2 rounded-lg border border-ink-3/30 bg-paper text-sm focus:outline-none focus:ring-2 focus:ring-orange/40"
            />
            <button
              type="button"
              onClick={saveLocation}
              disabled={
                savingLocation ||
                !locationInput.trim() ||
                locationInput.trim() === (profile.location ?? "")
              }
              className="px-4 py-2 rounded-lg bg-ink text-paper text-sm hover:bg-ink-2 transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {savingLocation ? "Saving…" : "Save"}
            </button>
          </div>
          {locationSaved ? (
            <p className="mt-2 text-xs text-green font-medium">Saved</p>
          ) : null}
        </div>
      </section>

      {/* Linked marketplaces */}
      <section className="flex flex-col gap-3">
        <h2 className="font-display text-lg text-ink">Linked marketplaces</h2>
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
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {MARKETPLACES.map((m) => (
            <AccountMarketplaceTile
              key={m.provider}
              provider={m.provider}
              label={m.label}
              sub={m.sub}
              comingSoon={Boolean(m.comingSoon)}
              comingSoonReason={m.comingSoonReason}
              row={linkedByProvider[m.provider]}
              stage={tileStage[m.provider]}
              onLink={() => handleLink(m.provider)}
              onFinish={() => handleFinishLink(m.provider)}
              onUnlink={() => handleUnlink(m.provider, m.label)}
            />
          ))}
        </div>
      </section>

      {/* Account actions */}
      <section className="flex flex-col gap-3">
        <h2 className="font-display text-lg text-ink">Account actions</h2>
        <div className="rounded-2xl bg-paper-2 border border-ink-3/15 px-5 py-5 flex flex-col gap-3">
          <button
            type="button"
            onClick={() => signOut({ callbackUrl: "/login" })}
            className="self-start px-4 py-2 rounded-lg bg-paper text-ink text-sm border border-ink-3/30 hover:bg-paper-3 transition"
          >
            Sign out
          </button>

          <div className="flex items-start gap-3">
            <button
              type="button"
              onClick={handleResetOnboarding}
              disabled={resetting}
              className="px-4 py-2 rounded-lg bg-paper text-ink text-sm border border-ink-3/30 hover:bg-paper-3 transition disabled:opacity-50"
            >
              {resetting ? "Resetting…" : "Re-run onboarding"}
            </button>
            <p className="text-xs text-ink-3 self-center">
              Resets the onboarding flag — your hunts + jobs are kept.
            </p>
          </div>
          {resetMessage ? (
            <p className="text-xs text-ink-2">{resetMessage}</p>
          ) : null}

          <div className="border-t border-ink-3/10 pt-4 mt-2">
            <div className="text-sm font-medium text-ink mb-2">
              Danger zone
            </div>
            <button
              type="button"
              onClick={() => {
                setDeleteOpen(true);
                setDeleteConfirmText("");
                setDeleteError(null);
              }}
              className="px-4 py-2 rounded-lg bg-red-600 text-paper text-sm font-medium hover:bg-red-700 transition"
              style={{ backgroundColor: "#b91c1c" }}
            >
              Delete account
            </button>
          </div>
        </div>
      </section>

      {/* Delete confirmation modal — bespoke (no shared modal primitive
          used elsewhere in this codebase). Keyboard-dismissable via the
          Cancel button + the overlay click. */}
      {deleteOpen ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="delete-account-title"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
          onClick={(e) => {
            if (e.target === e.currentTarget && !deleting) {
              setDeleteOpen(false);
            }
          }}
        >
          <div className="w-full max-w-md rounded-2xl bg-white shadow-paper px-6 py-6 flex flex-col gap-4">
            <h3
              id="delete-account-title"
              className="font-display text-xl text-ink"
            >
              Delete your account?
            </h3>
            <p className="text-sm text-ink-2 leading-relaxed">
              This deletes your account and all hunts, jobs, messages, and
              approvals. This cannot be undone.
            </p>
            <div className="flex flex-col gap-1">
              <label
                htmlFor="delete-confirm"
                className="text-xs text-ink-3 uppercase tracking-wide"
              >
                Type <span className="font-mono text-ink">DELETE</span> to
                confirm
              </label>
              <input
                id="delete-confirm"
                type="text"
                value={deleteConfirmText}
                onChange={(e) => setDeleteConfirmText(e.target.value)}
                className="px-3 py-2 rounded-lg border border-ink-3/30 bg-paper text-sm focus:outline-none focus:ring-2 focus:ring-red/40"
                autoFocus
                disabled={deleting}
              />
            </div>
            {deleteError ? (
              <ErrorMessage title="Delete failed" body={deleteError} />
            ) : null}
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setDeleteOpen(false)}
                disabled={deleting}
                className="px-4 py-2 rounded-lg bg-paper text-ink text-sm border border-ink-3/30 hover:bg-paper-3 transition disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmDelete}
                disabled={deleteConfirmText !== "DELETE" || deleting}
                className="px-4 py-2 rounded-lg text-paper text-sm font-medium transition disabled:opacity-50 disabled:cursor-not-allowed"
                style={{
                  backgroundColor:
                    deleteConfirmText === "DELETE" && !deleting
                      ? "#b91c1c"
                      : "#9ca3af",
                }}
              >
                {deleting ? "Deleting…" : "Delete account"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

interface AccountMarketplaceTileProps {
  provider: MarketplaceProvider;
  label: string;
  sub: string;
  comingSoon: boolean;
  comingSoonReason?: string;
  row: IntegrationAccount | null;
  stage: TileStage;
  onLink: () => void;
  onFinish: () => void;
  onUnlink: () => void;
}

function AccountMarketplaceTile({
  label,
  sub,
  comingSoon,
  comingSoonReason,
  row,
  stage,
  onLink,
  onFinish,
  onUnlink,
}: AccountMarketplaceTileProps) {
  const linked = Boolean(row?.linked);
  if (comingSoon) {
    return (
      <div
        className="rounded-2xl border px-5 py-4 flex flex-col gap-3 bg-paper-2/60 border-ink-3/10 opacity-70"
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
      className={`rounded-2xl border px-5 py-4 flex flex-col gap-3 bg-white ${
        linked ? "border-green/30" : "border-ink-3/15"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="font-medium text-ink truncate">{label}</div>
          <div className="text-xs text-ink-3 truncate">{sub}</div>
          {linked && row?.linked_at ? (
            <div className="text-xs text-ink-3 mt-1">
              Linked {formatMemberSince(row.linked_at)}
            </div>
          ) : null}
        </div>
        {linked ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-green/15 px-2 py-0.5 text-xs font-medium text-green">
            <span aria-hidden>✓</span> Linked
          </span>
        ) : stage === "tab_open" || stage === "finishing" ? (
          <span className="inline-flex items-center rounded-full bg-yellow/20 px-2 py-0.5 text-xs font-medium text-ink">
            Logging in…
          </span>
        ) : (
          <span className="inline-flex items-center rounded-full bg-paper-2 px-2 py-0.5 text-xs font-medium text-ink-3">
            Not linked
          </span>
        )}
      </div>
      <div className="flex gap-2">
        {linked ? (
          <>
            <button
              type="button"
              onClick={onLink}
              disabled={stage !== "idle"}
              className="flex-1 px-3 py-1.5 rounded-lg bg-ink text-paper text-sm hover:bg-ink-2 transition disabled:opacity-50"
            >
              {stage === "opening" ? "Opening…" : "Relink"}
            </button>
            <button
              type="button"
              onClick={onUnlink}
              disabled={stage !== "idle"}
              className="flex-1 px-3 py-1.5 rounded-lg bg-paper text-ink text-sm border border-ink-3/30 hover:bg-paper-3 transition disabled:opacity-50"
            >
              {stage === "unlinking" ? "Unlinking…" : "Unlink"}
            </button>
          </>
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
