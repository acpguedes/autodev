/** A single labeled metric shown in the Plans screen's stat-card row. */
export interface StatCardProps {
  /** Short uppercase label describing the metric. */
  label: string;
  /** The metric's current value. */
  value: number | string;
}

/**
 * Compact stat card (label + large value) used at the top of the Plans
 * screen to summarize the loaded plan (§18.7.11, prototype §5.2).
 */
export function StatCard({ label, value }: StatCardProps) {
  return (
    <div className="flex flex-col gap-1 rounded-ds-md border border-ds-line bg-ds-bg-2 p-4 shadow-ds-sm">
      <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-ds-fg-3">{label}</p>
      <p className="font-serif text-3xl font-semibold text-ds-fg">{value}</p>
    </div>
  );
}
