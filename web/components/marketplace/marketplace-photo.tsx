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
}: MarketplacePhotoProps) {
  const variant: PhotoVariant = photoVariantFor(listingId);
  const palette = VARIANT_BG[variant];

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
        {/* Background gradient + subtle paper noise */}
        <div
          className="absolute inset-0 paper-noise"
          style={{
            background: `linear-gradient(180deg, ${palette.from} 0%, ${palette.to} 100%)`,
          }}
        />
        {/* Floor line / depth cue */}
        <div
          className="absolute left-0 right-0"
          style={{
            bottom: "26%",
            height: "1px",
            background: palette.floor,
            opacity: 0.7,
          }}
        />
        {/* Soft cast shadow under object */}
        <div
          className="absolute left-1/2 -translate-x-1/2 rounded-[50%]"
          style={{
            bottom: "20%",
            width: "62%",
            height: "10px",
            background: palette.shadow,
            filter: "blur(6px)",
          }}
        />
        {/* Desk silhouette: top + two leg posts. No cartoon. */}
        <svg
          aria-hidden
          viewBox="0 0 100 60"
          preserveAspectRatio="none"
          className="absolute left-[12%] right-[12%]"
          style={{ bottom: "26%", width: "76%", height: "45%" }}
        >
          {/* Top surface */}
          <rect x="0" y="20" width="100" height="6" rx="1" fill={palette.object} />
          {/* Underside shade */}
          <rect x="0" y="26" width="100" height="1.5" fill={palette.object} opacity="0.55" />
          {/* Left leg */}
          <rect x="6" y="26" width="3.2" height="32" fill={palette.object} />
          {/* Right leg */}
          <rect x="90.8" y="26" width="3.2" height="32" fill={palette.object} />
          {/* Crossbar */}
          <rect x="9" y="40" width="82" height="1.5" fill={palette.object} opacity="0.7" />
        </svg>

        {/* Platform badge — bottom left */}
        <div className="absolute bottom-2 left-2">
          <MarketplaceBadge marketplace={marketplace} size="sm" />
        </div>
        {/* Photo count label — bottom right */}
        <div className="absolute bottom-2 right-2 rounded-full bg-ink/85 px-2 py-0.5 text-micro text-paper">
          {showThumbs ? "3 photos" : "1 photo"}
        </div>
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

      {showThumbs ? (
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
