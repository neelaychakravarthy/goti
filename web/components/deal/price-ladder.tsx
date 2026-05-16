import { cn } from "@/lib/utils";
import type { PriceLadder } from "@/types";

interface PriceLadderProps {
  ladder: PriceLadder;
}

interface Row {
  label: string;
  amount: number;
  ring?: "orange" | "green";
}

export function PriceLadderView({ ladder }: PriceLadderProps) {
  const rows: Row[] = [
    { label: "Your max", amount: ladder.your_max },
    { label: "Seller asks", amount: ladder.seller_asks },
    { label: "Goti recommends", amount: ladder.goti_recommends, ring: "orange" },
    { label: "Competing seller", amount: ladder.competing_seller, ring: "green" },
  ];

  return (
    <div className="rounded-xl border bg-paper-2 p-3 flex flex-col gap-1.5" style={{ borderColor: "rgba(15,15,15,0.12)" }}>
      {rows.map((r) => (
        <div
          key={r.label}
          className={cn(
            "flex items-center justify-between gap-3 rounded-lg px-3 py-2 bg-paper border",
            r.ring === "orange" && "ring-2 ring-orange/70",
            r.ring === "green" && "ring-2 ring-green/70",
            r.ring ? "" : ""
          )}
          style={{ borderColor: "rgba(15,15,15,0.1)" }}
        >
          <span className="text-caption text-ink-2 font-medium">{r.label}</span>
          <span className="font-display font-bold text-body text-ink">
            ${r.amount}
          </span>
        </div>
      ))}
    </div>
  );
}
