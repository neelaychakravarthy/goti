import { cn } from "@/lib/utils";

interface TwoPanelProps {
  children: React.ReactNode;
  aside: React.ReactNode;
  className?: string;
  /** Width of the aside on desktop. Defaults to 4 of 12 cols. */
  asideCols?: 3 | 4 | 5;
}

/**
 * Workspace shell: main content on the left, Next Moves rail on the right.
 * Stacks vertically below `lg`.
 */
export function TwoPanel({
  children,
  aside,
  className,
  asideCols = 4,
}: TwoPanelProps) {
  const mainCols = 12 - asideCols;
  return (
    <div className={cn("grid grid-cols-12 gap-6", className)}>
      <div
        className={cn(
          "col-span-12 min-w-0",
          mainCols === 7 && "lg:col-span-7",
          mainCols === 8 && "lg:col-span-8",
          mainCols === 9 && "lg:col-span-9"
        )}
      >
        {children}
      </div>
      <aside
        className={cn(
          "col-span-12",
          asideCols === 3 && "lg:col-span-3",
          asideCols === 4 && "lg:col-span-4",
          asideCols === 5 && "lg:col-span-5"
        )}
      >
        {aside}
      </aside>
    </div>
  );
}
