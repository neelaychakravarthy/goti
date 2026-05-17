import { MarketplaceBadge } from "@/components/marketplace/marketplace-badge";
import { cn, photoVariantFor, type PhotoVariant } from "@/lib/utils";
import type { Marketplace } from "@/types";

interface MarketplacePhotoProps {
  listingId: string;
  marketplace: Marketplace;
  size?: "sm" | "md" | "lg";
  showThumbs?: boolean;
  cornerSticker?: string;
  className?: string;
  /** Real listing image URL (from the marketplace). When supplied and
   * it looks like a real http(s) URL, the component renders the
   * actual image. Otherwise falls back to a neutral marketplace-
   * themed panel — no fake desk silhouette regardless of category. */
  imageUrl?: string | null;
}

function isRealImageUrl(v: string | null | undefined): v is string {
  if (!v) return false;
  return v.startsWith("http://") || v.startsWith("https://");
}

// Deterministic palettes. Tuned to read as real listing photo crops, not
// cartoons — soft tonal background, a single object silhouette with simple
// horizontal "desk-on-floor" depth cue.
const VARIANT_BG: Record<PhotoVariant, { from: string; to: string; floor: string; object: string; shadow: string }> = {
  peach: {
    from: "#F8D9C2",
    to: "#E9B791",
    floor: "#C99879",
    object: "#3D2A1F",
    shadow: "rgba(53,30,17,0.18)",
  },
  mint: {
    from: "#D9EAE0",
    to: "#A8C6B6",
    floor: "#7AA290",
    object: "#1F3327",
    shadow: "rgba(31,51,39,0.18)",
  },
  neutral: {
    from: "#E6E3DC",
    to: "#BFBAAE",
    floor: "#8B8678",
    object: "#2A2620",
    shadow: "rgba(42,38,32,0.18)",
  },
};

/**
 * Realistic marketplace photo placeholder: paper-toned gradient bg with a
 * simple object silhouette (desk surface + 2 legs), platform badge in one
 * corner, "2 photos" label in another. Deterministic palette per listing id.
 * No cartoon illustrations — this reads as a low-res seller photo crop.
 */
export function MarketplacePhoto({
  listingId,
  marketplace,
  size = "md",
  showThumbs = true,
  cornerSticker,
  className,
  imageUrl,
}: MarketplacePhotoProps) {
  const variant: PhotoVariant = photoVariantFor(listingId);
  const palette = VARIANT_BG[variant];
  const hasRealImage = isRealImageUrl(imageUrl);

  const heights = {
    sm: "h-32",
    md: "h-44",
    lg: "h-60",
  };

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div
        className={cn(
          "relative w-full overflow-hidden rounded-lg border border-ink-line/15",
          heights[size]
        )}
      >
        {hasRealImage ? (
          // Real listing photo — render it. ``object-cover`` crops to
          // the panel; alt is empty so screen readers skip the redundant
          // image (the listing title is announced separately).
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={imageUrl as string}
            alt=""
            className="absolute inset-0 h-full w-full object-cover"
            loading="lazy"
            referrerPolicy="no-referrer"
          />
        ) : (
          // NEUTRAL fallback panel — marketplace-themed gradient with
          // a centered "no photo" subtitle. Deliberately category-
          // agnostic: no fake desk / shoe / couch silhouette. The
          // marketplace badge below tells the user where the listing
          // is from.
          <>
            <div
              className="absolute inset-0 paper-noise"
              style={{
                background: `linear-gradient(180deg, ${palette.from} 0%, ${palette.to} 100%)`,
              }}
            />
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 text-ink-2">
              <svg
                aria-hidden
                viewBox="0 0 24 24"
                className="size-7 opacity-50"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <rect x="3" y="5" width="18" height="14" rx="2" />
                <circle cx="9" cy="11" r="1.5" />
                <path d="m21 17-5-5L8 19" />
              </svg>
              <span className="text-micro uppercase tracking-[0.08em] text-ink-3">
                No photo
              </span>
            </div>
          </>
        )}

        {/* Platform badge — bottom left */}
        <div className="absolute bottom-2 left-2">
          <MarketplaceBadge marketplace={marketplace} size="sm" />
        </div>
        {/* Photo count label — bottom right. Only meaningful when we
            have a real image; otherwise it'd lie ("3 photos" with
            none rendered). */}
        {hasRealImage ? (
          <div className="absolute bottom-2 right-2 rounded-full bg-ink/85 px-2 py-0.5 text-micro text-paper">
            {showThumbs ? "photos" : "1 photo"}
          </div>
        ) : null}
        {/* Optional yellow corner sticker (e.g. "listing photo") */}
        {cornerSticker ? (
          <div
            className="absolute top-2 right-2 rounded-md border bg-yellow px-2 py-0.5 text-micro font-medium text-ink shadow-[0_2px_0_0_rgba(0,0,0,1)]"
            style={{ borderColor: "var(--yellow-deep)", transform: "rotate(2deg)" }}
          >
            {cornerSticker}
          </div>
        ) : null}
      </div>

      {showThumbs && hasRealImage ? (
        <div className="flex gap-2">
          {[0, 1].map((idx) => (
            <div
              key={idx}
              className={cn(
                "relative h-12 w-1/2 overflow-hidden rounded-md border border-ink-line/15"
              )}
            >
              <div
                className="absolute inset-0 paper-noise"
                style={{
                  background: `linear-gradient(${idx === 0 ? 180 : 165}deg, ${
                    palette.from
                  } 0%, ${palette.to} 100%)`,
                  filter: idx === 0 ? "brightness(0.95)" : "brightness(1.05)",
                }}
              />
              <svg
                aria-hidden
                viewBox="0 0 100 60"
                preserveAspectRatio="none"
                className="absolute left-[18%] right-[18%]"
                style={{
                  bottom: idx === 0 ? "22%" : "28%",
                  width: "64%",
                  height: "40%",
                }}
              >
                <rect x="0" y="22" width="100" height="6" rx="1" fill={palette.object} />
                <rect x="10" y="28" width="3" height="26" fill={palette.object} />
                <rect x="87" y="28" width="3" height="26" fill={palette.object} />
              </svg>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
