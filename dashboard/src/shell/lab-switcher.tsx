/* oxlint-disable jsx-a11y/prefer-tag-over-role, jsx-a11y/no-noninteractive-element-interactions -- ARIA listbox pattern (as in Spotlight); the dialog takes arrow keys and a backdrop click to close, Escape is native */
/**
 * Lab switcher — the ⌘L / Ctrl+L compact modal that focuses the sidebar on one lab.
 * A native <dialog> like Spotlight: a compact card per lab with its live availability on this
 * computer and a one-line summary, arrow keys to move, Enter to pick, and "All labs" at the foot
 * to clear the focus and list every lab in the sidebar again.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  KeyReturnIcon,
  SquaresFourIcon,
  XIcon
} from "@phosphor-icons/react";
import { cn } from "./sidebar";
import type { ActiveLabId } from "./active-lab";

export interface LabSwitcherLab {
  id: ActiveLabId;
  label: string;
  icon: ReactNode;
  /** One line under the label: what the lab does, from its live report on this computer. */
  summary?: string;
  /** Availability pill or running dot, built from the same report as the sidebar's. */
  badge?: ReactNode;
}

interface LabSwitcherProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  labs: LabSwitcherLab[];
  /** The lab the sidebar currently focuses on, if any. */
  activeLab: ActiveLabId | null;
  onPick: (lab: ActiveLabId) => void;
  /** Clears the focus so the sidebar lists every lab again. */
  onShowAll: () => void;
}

const kbd =
  "inline-flex h-5 min-w-5 items-center justify-center rounded border border-(--iux-border) bg-(--iux-muted) px-1 text-[11px] text-(--iux-muted-foreground)";

export function LabSwitcher({ open, onOpenChange, labs, activeLab, onPick, onShowAll }: LabSwitcherProps) {
  const [picked, setPicked] = useState<number | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      // Start on the focused lab's card, or the first one
      setPicked(activeLab ? labs.findIndex((lab) => lab.id === activeLab) : 0);
      dialog.showModal();
      // Focus the dialog, not its first card, so Enter picks the highlight (as in Spotlight's input)
      dialog.focus();
    }
    if (!open && dialog.open) dialog.close();
  }, [open, activeLab, labs]);

  const index = picked !== null && picked >= 0 && picked < labs.length ? picked : 0;

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (labs.length === 0) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setPicked((index + (e.key === "ArrowDown" ? 1 : -1) + labs.length) % labs.length);
    } else if (e.key === "Enter" && e.target === dialogRef.current) {
      // Enter on a focused card activates that card; only the dialog itself picks the highlight
      e.preventDefault();
      const lab = labs[index];
      if (lab) onPick(lab.id);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      tabIndex={-1}
      aria-label="Switch lab"
      className="iux iux-dialog iux-lab-switcher"
      onKeyDown={onKeyDown}
      // Escape closes the native dialog; keep React state in step
      onClose={() => {
        if (open) onOpenChange(false);
      }}
      // A click on the backdrop lands on the dialog element itself
      onClick={(e) => {
        if (e.target === e.currentTarget) onOpenChange(false);
      }}
    >
      {open && (
        <>
          <header className="flex items-center gap-2.5 border-b border-(--iux-border) py-2.5 pr-2 pl-4">
            <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-(--iux-accent) text-(--iux-foreground)">
              <SquaresFourIcon size={15} />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-sm leading-5 font-semibold">Switch lab</h2>
              <p className="truncate text-xs leading-4 text-(--iux-muted-foreground)">Focus the sidebar on one lab</p>
            </div>
            <kbd className={kbd}>⌘L</kbd>
            <button
              type="button"
              className="iux-btn shrink-0"
              data-variant="ghost"
              data-size="icon"
              aria-label="Close"
              onClick={() => onOpenChange(false)}
            >
              <XIcon size={16} />
            </button>
          </header>
          <div
            role="listbox"
            aria-label="Labs"
            className="iux-scroll flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto p-2"
          >
            {labs.map((lab, i) => {
              const isActive = i === index;
              return (
                <button
                  key={lab.id}
                  type="button"
                  role="option"
                  aria-selected={isActive}
                  data-active={isActive}
                  onMouseMove={() => setPicked(i)}
                  onClick={() => onPick(lab.id)}
                  className={cn(
                    "flex items-center gap-3 rounded-lg border px-3 py-2 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-(--iux-ring)",
                    isActive
                      ? "border-(--iux-primary)/40 bg-(--iux-accent)"
                      : "border-transparent hover:bg-(--iux-accent)/60"
                  )}
                >
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-(--iux-border) bg-(--iux-muted) text-(--iux-foreground)">
                    {lab.icon}
                  </span>
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate text-sm font-medium">{lab.label}</span>
                    {lab.summary && (
                      <span className="truncate text-xs text-(--iux-muted-foreground)">{lab.summary}</span>
                    )}
                  </span>
                  {lab.badge}
                </button>
              );
            })}
          </div>
          <footer className="flex items-center gap-4 border-t border-(--iux-border) bg-(--iux-muted)/40 px-4 py-2.5 text-xs text-(--iux-muted-foreground)">
            <span className="inline-flex items-center gap-1.5">
              <kbd className={kbd}>
                <ArrowUpIcon size={11} />
              </kbd>
              <kbd className={kbd}>
                <ArrowDownIcon size={11} />
              </kbd>
              <span className="inline-flex items-center gap-1">
                <kbd className={kbd}>
                  <KeyReturnIcon size={11} />
                </kbd>
                to switch
              </span>
            </span>
            {activeLab && (
              <button
                type="button"
                onClick={onShowAll}
                className="ml-auto rounded-md border border-(--iux-border) px-2 py-1 text-xs transition-colors hover:bg-(--iux-accent)/60"
              >
                All labs
              </button>
            )}
          </footer>
        </>
      )}
    </dialog>
  );
}
