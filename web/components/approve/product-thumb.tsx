import { cn, photoVariantFor, type PhotoVariant } from "@/lib/utils";

interface ProductThumbProps {
  listingId: string;
  className?: string;
  size?: 40 | 48 | 56;
  alt?: string;
}

const VARIANT_BG: Record<PhotoVariant, { from: string; to: string; object: string }> = {
  peach:   { from: "#F8D9C2", to: "#E9B791", object: "#3D2A1F" },
  mint:    { from: "#D9EAE0", to: "#A8C6B6", object: "#1F3327" },
  neutral: { from: "#E6E3DC", to: "#BFBAAE", object: "#2A2620" },
};

/**
 * Small marketplace-photo variant for use in the approval ticket header.
 * Same deterministic palette per listing id as MarketplacePhoto so the
 * thumbnail reads as the same product.
 */
export function ProductThumb({
  listingId,
  className,
  size = 48,
  alt,
}: ProductThumbProps) {
  const variant = photoVariantFor(listingId);
  const palette = VARIANT_BG[variant];

  return (
    <div
      role={alt ? "img" : undefined}
      aria-label={alt}
      className={cn(
        "relative shrink-0 overflow-hidden rounded-lg border border-ink-line/20",
        className
      )}
      style={{ width: size, height: size }}
    >
      <div
        className="absolute inset-0 paper-noise"
        style={{
          background: `linear-gradient(180deg, ${palette.from} 0%, ${palette.to} 100%)`,
        }}
      />
      <svg
        aria-hidden
        viewBox="0 0 100 60"
        preserveAspectRatio="none"
        className="absolute left-[14%] right-[14%]"
        style={{ bottom: "24%", width: "72%", height: "44%" }}
      >
        <rect x="0" y="20" width="100" height="6" rx="1" fill={palette.object} />
        <rect x="6" y="26" width="3.2" height="32" fill={palette.object} />
        <rect x="90.8" y="26" width="3.2" height="32" fill={palette.object} />
      </svg>
    </div>
  );
}
