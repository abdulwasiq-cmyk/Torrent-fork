export type SortDirection = 'desc' | 'asc';

export type SortBarOption = { key: string; label: string };

const ACTIVE = 'rounded-lg px-3 py-2 text-xs font-bold bg-cyan-500 text-slate-950';
const IDLE = 'rounded-lg px-3 py-2 text-xs font-bold bg-slate-950 text-slate-400 border border-slate-800 hover:text-slate-200';

/**
 * The one sort control used by every section: "Sort by" + the available keys in the order
 * Popularity, Rating, Year. The active key shows its direction (newest/highest first by
 * default); pressing it again reverses the order, pressing another key selects it.
 */
export function SortBar({ options, active, direction, onSelect }: {
  options: SortBarOption[];
  active: string;
  direction: SortDirection;
  onSelect: (key: string) => void;
}) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border border-slate-800 bg-slate-950/70 px-2.5 py-2.5" role="group" aria-label="Sort">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Sort by</span>
      {options.map(option => {
        const isActive = option.key === active;
        return (
          <button
            key={option.key}
            type="button"
            aria-pressed={isActive}
            title={isActive ? 'Click to reverse the order' : 'Sort by ' + option.label.toLowerCase()}
            onClick={() => onSelect(option.key)}
            className={isActive ? ACTIVE : IDLE}
          >
            {option.label}{isActive ? (direction === 'asc' ? ' ↑' : ' ↓') : ''}
          </button>
        );
      })}
    </div>
  );
}

/** Reverse a sorted list when the direction is ascending. */
export function applySortDirection<T>(rows: T[], direction: SortDirection): T[] {
  return direction === 'asc' ? rows.slice().reverse() : rows;
}
