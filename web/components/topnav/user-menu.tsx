"use client";

// Top-nav user widget: avatar (Google picture) + dropdown with
// "Account" + "Sign out".

import Link from "next/link";
import { signOut, useSession } from "next-auth/react";
import { useState } from "react";

export function UserMenu() {
  const { data: session, status } = useSession();
  const [open, setOpen] = useState(false);

  if (status === "loading" || !session?.user) {
    return null;
  }

  const name = session.user.name ?? session.user.email ?? "Account";
  const initial = (name[0] ?? "?").toUpperCase();
  const picture = session.user.image;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-full border border-ink-3/10 bg-paper-2 px-2 py-1 hover:bg-ink-3/10"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        {picture ? (
          // Plain <img> rather than next/image so we don't need to allow-list
          // Google's image domain in next.config.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={picture}
            alt={name}
            className="h-6 w-6 rounded-full"
            referrerPolicy="no-referrer"
          />
        ) : (
          <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-ink-3/20 text-xs">
            {initial}
          </span>
        )}
        <span className="hidden md:inline text-micro text-ink-2">{name}</span>
      </button>
      {open && (
        // Opens UPWARD (``bottom-full``) because UserMenu lives at the
        // bottom of the LEFT sidebar — top-anchored would clip off the
        // bottom of the viewport. Opens RIGHTWARD (``left-0``) because
        // ``right-0`` would extend the 180px menu off-screen to the
        // left of the viewport.
        <div
          role="menu"
          className="absolute left-0 bottom-full mb-2 min-w-[180px] rounded-xl border border-ink-3/10 bg-white shadow-paper p-1 text-sm z-30"
        >
          <div className="px-3 py-2 text-ink-2 truncate">
            {session.user.email}
          </div>
          <Link
            href="/account"
            onClick={() => setOpen(false)}
            className="block w-full text-left px-3 py-2 rounded-lg hover:bg-paper-2 text-ink"
            role="menuitem"
          >
            Account
          </Link>
          <button
            type="button"
            onClick={() => signOut({ callbackUrl: "/login" })}
            className="block w-full text-left px-3 py-2 rounded-lg hover:bg-paper-2 text-ink"
            role="menuitem"
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
