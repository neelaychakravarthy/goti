import type { SavingsReceipt } from "@/types";

interface SavingsReceiptProps {
  savings: SavingsReceipt;
}

export function SavingsReceiptView({ savings }: SavingsReceiptProps) {
  return (
    <div
      className="rounded-xl border bg-yellow text-ink p-3.5 shadow-[0_2px_0_0_rgba(0,0,0,1)]"
      style={{ borderColor: "var(--yellow-deep)" }}
    >
      <div className="text-micro uppercase tracking-wider font-semibold text-ink-2 mb-1">
        Savings receipt
      </div>
      <div className="text-caption text-ink leading-relaxed">
        <span>{`If accepted: `}</span>
        <strong className="font-semibold">{`pay $${savings.pay}`}</strong>
        <span className="text-ink-2">{" · "}</span>
        <strong className="font-semibold">{`save $${savings.save_vs_asking}`}</strong>
        <span>{` vs asking `}</span>
        <span className="text-ink-2">{"· "}</span>
        <strong className="font-semibold">{`stay $${savings.under_budget}`}</strong>
        <span>{` under budget`}</span>
      </div>
    </div>
  );
}
