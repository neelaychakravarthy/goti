import type { ReactNode } from "react";

type MarkKind = "glyph" | "wordmark";

interface PlatformItem {
  name: string;
  color: string;
  /** "glyph" = small mark + text label. "wordmark" = SVG IS the name. */
  kind: MarkKind;
  svg: ReactNode;
}

/**
 * Real platform marks (inlined SVG). currentColor lets a single platform color
 * var drive both glyph + label. Two render modes:
 *   - glyph:    [ icon · "Name" ]              (most platforms)
 *   - wordmark: [ <wordmark-svg only> ]        (eBay, Nextdoor — SVG includes the name)
 */
const PLATFORMS: PlatformItem[] = [
  {
    name: "Facebook Marketplace",
    color: "var(--mk-facebook)",
    kind: "glyph",
    svg: (
      <svg
        viewBox="0 0 24 24"
        aria-hidden
        className="size-5"
        fill="currentColor"
      >
        <path d="M9.101 23.691v-7.98H6.627v-3.667h2.474v-1.58c0-4.085 1.848-5.978 5.858-5.978.401 0 .955.042 1.468.103a8.68 8.68 0 0 1 1.141.195v3.325a8.623 8.623 0 0 0-.653-.036 26.805 26.805 0 0 0-.733-.009c-.707 0-1.259.096-1.675.309a1.686 1.686 0 0 0-.679.622c-.258.42-.374.995-.374 1.752v1.297h3.919l-.386 2.103-.287 1.564h-3.246v8.245C19.396 23.238 24 18.179 24 12.044c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.628 3.874 10.35 9.101 11.647Z" />
      </svg>
    ),
  },
  {
    name: "Nextdoor",
    color: "var(--mk-nextdoor)",
    kind: "wordmark",
    svg: (
      <svg
        viewBox="0 0 24 24"
        aria-hidden
        className="h-4 w-auto"
        fill="currentColor"
      >
        <path d="M14.65 9.997a.069.069 0 0 0-.07.069v1.415c-.123-.177-.42-.37-.805-.37-.745 0-1.316.659-1.316 1.445 0 .787.571 1.447 1.316 1.447.386 0 .682-.194.806-.372v.221c0 .05.04.09.09.09h.607a.07.07 0 0 0 .07-.07v-3.806a.069.069 0 0 0-.07-.069zm-3.913.404a.07.07 0 0 0-.069.07c0 .779.064.7-.504.7a.09.09 0 0 0-.09.09v.486c0 .05.04.089.09.089h.504v1.136c0 .676.476 1.003 1.07 1.003.183 0 .32-.017.434-.046a.07.07 0 0 0 .052-.067v-.526a.07.07 0 0 0-.086-.066.984.984 0 0 1-.227.023c-.33 0-.476-.133-.476-.47v-.987h.608a.07.07 0 0 0 .07-.069v-.527a.069.069 0 0 0-.07-.069h-.608v-.701a.069.069 0 0 0-.069-.07zm-8.396.676c-.516 0-.955.236-1.201.598-.02.03-.055.095-.102.095-.226.002-.24-.276-.247-.524a.07.07 0 0 0-.069-.066l-.653-.004a.07.07 0 0 0-.069.07c.014.606.126 1.018.86 1.181.04.01.068.045.068.087v1.36c0 .037.03.068.069.068h.634a.07.07 0 0 0 .069-.07V12.47c0-.312.221-.667.64-.667.4 0 .642.355.642.667v1.404c0 .038.03.069.069.069h.634a.07.07 0 0 0 .069-.07v-1.508c0-.72-.616-1.287-1.413-1.287zm3.207.033c-.851 0-1.472.626-1.472 1.446 0 .876.65 1.431 1.483 1.447.655.012 1.09-.363 1.194-.494a.068.068 0 0 0-.015-.097l-.435-.34c-.047-.047-.084-.021-.112.001-.07.057-.203.22-.626.237-.37.015-.7-.205-.745-.576h2.03a.07.07 0 0 0 .069-.065c.006-.082.006-.142.006-.196 0-.897-.644-1.363-1.377-1.363zm11.652 0c-.812 0-1.472.637-1.472 1.446 0 .81.66 1.447 1.472 1.447.812 0 1.472-.638 1.472-1.447s-.66-1.446-1.472-1.446zm3.229 0c-.812 0-1.472.637-1.472 1.446 0 .81.66 1.447 1.472 1.447.812 0 1.472-.638 1.472-1.447s-.66-1.446-1.472-1.446zm3.314.028a.745.745 0 0 0-.695.476v-.374a.069.069 0 0 0-.069-.069h-.628a.069.069 0 0 0-.07.07v2.632a.07.07 0 0 0 .07.069h.628a.07.07 0 0 0 .07-.07v-1.255c0-.454.24-.737.604-.737.092 0 .175.013.26.035A.069.069 0 0 0 24 11.85v-.624a.07.07 0 0 0-.056-.068.938.938 0 0 0-.201-.02zm-16.666.033a.069.069 0 0 0-.058.108l.88 1.305L7 13.832a.07.07 0 0 0 .056.11h.745a.068.068 0 0 0 .056-.03l.564-.79.563.79a.069.069 0 0 0 .056.03h.74a.069.069 0 0 0 .057-.11l-.899-1.248.88-1.305a.069.069 0 0 0-.058-.108h-.738a.07.07 0 0 0-.058.03l-.548.818-.549-.817a.07.07 0 0 0-.057-.03zm-1.552.565c.286 0 .566.155.633.482h-1.31c.073-.338.392-.482.677-.482zm8.412.067c.42 0 .705.321.705.753 0 .433-.285.754-.705.754s-.705-.321-.705-.754c0-.432.285-.753.705-.753zm3.263.016c.403 0 .694.31.694.737s-.291.737-.694.737c-.403 0-.7-.31-.7-.737 0-.426.297-.737.7-.737zm3.229 0c.403 0 .694.31.694.737s-.291.737-.694.737c-.403 0-.7-.31-.7-.737 0-.426.297-.737.7-.737z" />
      </svg>
    ),
  },
  {
    name: "craigslist",
    color: "var(--mk-craigslist)",
    kind: "glyph",
    svg: (
      <svg
        viewBox="0 0 48 48"
        aria-hidden
        className="size-5"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <circle cx="24" cy="24" r="21.5" />
        <path d="M24 2.5v42.992M24 24L8.798 39.202M24 24l15.202 15.202" />
      </svg>
    ),
  },
  {
    name: "OfferUp",
    color: "var(--mk-offerup)",
    kind: "glyph",
    svg: (
      <svg
        viewBox="0 0 48 48"
        aria-hidden
        className="size-5"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="m7.369 28.832l30.755-5.516l5.376-9.143l-8.245-5.958L4.5 13.73z" />
        <path d="m10.494 28.272l7.997 11.513l23.522-15.73l1.487-9.882" />
        <circle cx="39.339" cy="14.912" r="1.4" fill="currentColor" />
      </svg>
    ),
  },
  {
    name: "eBay",
    color: "var(--mk-ebay)",
    kind: "wordmark",
    svg: (
      <svg
        viewBox="0 0 24 24"
        aria-hidden
        className="h-4 w-auto"
        fill="currentColor"
      >
        <path d="M6.056 12.132v-4.92h1.2v3.026c.59-.703 1.402-.906 2.202-.906 1.34 0 2.828.904 2.828 2.855 0 .233-.015.457-.06.668.24-.953 1.274-1.305 2.896-1.344.51-.018 1.095-.018 1.56-.018v-.135c0-.885-.556-1.244-1.53-1.244-.72 0-1.245.3-1.305.81h-1.275c.136-1.29 1.5-1.62 2.686-1.62 1.064 0 1.995.27 2.415 1.02l-.436-.84h1.41l2.055 4.125 2.055-4.126H24l-3.72 7.305h-1.346l1.07-2.04-2.33-4.38c.13.255.2.555.2.93v2.46c0 .346.01.69.04 1.005H16.8a6.543 6.543 0 01-.046-.765c-.603.734-1.32.96-2.32.96-1.48 0-2.272-.78-2.272-1.695 0-.15.015-.284.037-.405-.3 1.246-1.36 2.086-2.767 2.086-.87 0-1.694-.315-2.2-.93 0 .24-.015.494-.04.734h-1.18c.02-.39.04-.855.04-1.245v-1.05h-4.83c.065 1.095.818 1.74 1.853 1.74.718 0 1.355-.3 1.568-.93h1.24c-.24 1.29-1.61 1.725-2.79 1.725C.95 15.009 0 13.822 0 12.232c0-1.754.982-2.91 3.116-2.91 1.688 0 2.93.886 2.94 2.806v.005zm9.137.183c-1.095.034-1.77.233-1.77.95 0 .465.36.97 1.305.97 1.26 0 1.935-.69 1.935-1.814v-.13c-.45 0-.99.006-1.484.022h.012zm-6.06 1.875c1.11 0 1.876-.806 1.876-2.02s-.768-2.02-1.893-2.02c-1.11 0-1.89.806-1.89 2.02s.765 2.02 1.875 2.02h.03zm-4.35-2.514c-.044-1.125-.854-1.546-1.725-1.546-.944 0-1.694.474-1.815 1.546z" />
      </svg>
    ),
  },
  {
    name: "Mercari",
    color: "var(--mk-mercari)",
    kind: "glyph",
    svg: (
      <svg
        viewBox="0 0 48 48"
        aria-hidden
        className="size-5"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M8.154 43.5V14.991L22.408 43.5l14.255-28.509V43.5M33.3 9.663L34.684 4.5l5.164 1.383l-1.384 5.164z" />
      </svg>
    ),
  },
  {
    name: "Poshmark",
    color: "var(--mk-poshmark)",
    kind: "glyph",
    svg: (
      <svg
        viewBox="0 0 48 48"
        aria-hidden
        className="size-5"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M27.198 15.945v16.373l-.005-.004c0 4.917-4.175 8.917-9.34 8.917s-9.353-4-9.353-8.917c0-4.51 3.52-8.234 8.074-8.816" />
        <path d="M20.805 32.047V15.675l.002-.003c0-4.917 4.175-8.903 9.34-8.903s9.353 3.986 9.353 8.903c0 4.582-3.637 8.364-8.321 8.844" />
      </svg>
    ),
  },
  {
    name: "Depop",
    color: "var(--mk-depop)",
    kind: "glyph",
    svg: (
      <svg
        viewBox="0 0 48 48"
        aria-hidden
        className="size-5"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M33.553 11.584v24.832m0-5.649H20.448c-3.324 0-6-2.675-6-6v-1.533c0-3.325 2.676-6 6-6H33.55" />
        <rect width="37" height="37" x="5.5" y="5.5" rx="4" ry="4" />
      </svg>
    ),
  },
  {
    name: "Local groups",
    color: "var(--mk-local)",
    kind: "glyph",
    svg: (
      <svg
        viewBox="0 0 20 20"
        aria-hidden
        className="size-5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M3 10.5 10 4l7 6.5" />
        <path d="M5 10v6h10v-6" />
      </svg>
    ),
  },
];

function PlatformPill({ item }: { item: PlatformItem }) {
  const baseClass =
    "inline-flex h-10 items-center gap-2 rounded-full border bg-paper-2 px-4 shrink-0 whitespace-nowrap";
  const style = { borderColor: "rgba(15,15,15,0.12)", color: item.color };

  if (item.kind === "wordmark") {
    return (
      <span className={baseClass} style={style} aria-label={item.name}>
        <span aria-hidden className="inline-flex items-center justify-center">
          {item.svg}
        </span>
      </span>
    );
  }

  return (
    <span className={baseClass} style={style}>
      <span aria-hidden className="inline-flex items-center justify-center">
        {item.svg}
      </span>
      <span className="text-caption font-medium" style={{ color: item.color }}>
        {item.name}
      </span>
    </span>
  );
}

/**
 * Continuously-scrolling marquee of marketplace marks shown below the /start
 * NL hero. Duplicates the row inline so the keyframe (translateX 0 → -50%)
 * loops seamlessly. Hover pauses; edge masks soften the loop seam.
 */
export function MarketplacesStrip9() {
  return (
    <div className="flex flex-col gap-3">
      <span className="text-micro uppercase tracking-wider text-ink-3 font-medium text-center">
        Searches across:
      </span>
      <div
        className="goti-marquee-pause goti-marquee-mask relative overflow-hidden"
        style={{ height: "48px" }}
      >
        <div className="goti-marquee-track flex items-center gap-3 h-full w-max">
          {PLATFORMS.map((p) => (
            <PlatformPill key={`a-${p.name}`} item={p} />
          ))}
          {PLATFORMS.map((p) => (
            <PlatformPill key={`b-${p.name}`} item={p} />
          ))}
        </div>
      </div>
    </div>
  );
}
