/**
 * Context menu for one catalog entry on the Advanced scan page: right-click, the ⋯ button or the
 * keyboard menu key opens it. Items are plain actions the page already has (scan this entry, plan a
 * clean, select, bookmark); a disabled item states why. Nothing here removes anything: "Review & clean"
 * only builds a plan, and the existing confirmation dialog opens before a clean can run.
 */
import { useEffect, useRef } from "react";

export interface EntryMenuItem {
  id: string;
  label: string;
  onSelect: () => void;
  /** Why the item cannot run right now; shown as its tooltip and description. */
  disabledReason?: string;
  tone?: "danger";
  separatorBefore?: boolean;
}

export interface EntryMenuState { x: number; y: number; entryId: string }

export function EntryMenu({ state, title, items, onClose }: {
  state: EntryMenuState; title: string; items: EntryMenuItem[]; onClose: () => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const onClose = () => closeRef.current();
    const openedAt = Date.now();
    // Layout shifts right after opening (focus, smooth scroll) must not close the menu.
    const onScroll = () => { if (Date.now() - openedAt > 250) onClose(); };
    const previous = document.activeElement as HTMLElement | null;
    root.current?.querySelector<HTMLButtonElement>("button:not([disabled])")?.focus({ preventScroll: true });
    const close = (event: Event) => { if (!root.current?.contains(event.target as Node)) onClose(); };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); return; }
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      event.preventDefault();
      const buttons = [...(root.current?.querySelectorAll<HTMLButtonElement>("button:not([disabled])") ?? [])];
      if (!buttons.length) return;
      const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
      const next = (at + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next]?.focus({ preventScroll: true });
    };
    document.addEventListener("pointerdown", close, true);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", onClose);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("pointerdown", close, true);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onClose);
      window.removeEventListener("scroll", onScroll, true);
      previous?.focus?.({ preventScroll: true });
    };
  }, []);

  // Keep the menu inside the viewport.
  const width = 224;
  const height = items.length * 34 + 40;
  const left = Math.max(8, Math.min(state.x, window.innerWidth - width - 8));
  const top = Math.max(8, Math.min(state.y, window.innerHeight - height - 8));

  return <div ref={root} role="menu" aria-label={title} style={{ left, top, width }}
    className="fixed z-50 rounded-md border border-(--iux-border) bg-(--iux-card) p-1 text-sm shadow-lg">
    <div className="truncate px-2 py-1 text-xs text-(--iux-muted-foreground)" translate="no">{title}</div>
    {items.map((item) => <div key={item.id}>
      {item.separatorBefore && <hr className="my-1 border-(--iux-border)" />}
      <button type="button" role="menuitem" disabled={!!item.disabledReason} title={item.disabledReason}
        className={`flex w-full items-center rounded px-2 py-1.5 text-start hover:bg-(--iux-muted) focus-visible:bg-(--iux-muted) disabled:cursor-not-allowed disabled:opacity-50 ${item.tone === "danger" ? "text-(--iux-danger)" : ""}`}
        onClick={() => { onClose(); item.onSelect(); }}>{item.label}</button>
    </div>)}
  </div>;
}
