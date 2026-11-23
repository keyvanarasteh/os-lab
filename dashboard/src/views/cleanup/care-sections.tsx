/**
 * CUX-09: the compact dashboard sections. Everything beyond the one primary action lives in
 * one bordered list of collapsed rows, each with a one-line live summary, so nothing is lost
 * and nothing competes with Scan & review. A row opens by itself when a link or the sidebar
 * targets its id, or when it needs attention (for example an active low-space alert).
 */
import { useEffect, useState } from "react";
import { CaretRightIcon } from "@phosphor-icons/react";

export function CareRow({ id, title, summary, attention, children }: {
  id: string; title: string; summary: React.ReactNode; attention?: boolean; children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const read = () => { if (decodeURIComponent(window.location.hash.slice(1)) === id) setOpen(true); };
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, [id]);
  return <details id={id} className="group" open={open} onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}>
    <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 text-sm">
      <CaretRightIcon size={12} aria-hidden="true" className="transition-transform group-open:rotate-90" />
      <span className="font-medium">{title}</span>
      {attention && <span aria-hidden="true" className="size-2 rounded-full bg-(--iux-danger)" />}
      <span className="ms-auto truncate text-xs text-(--iux-muted-foreground)">{summary}</span>
    </summary>
    <div className="border-t border-(--iux-border) px-3 py-3">{children}</div>
  </details>;
}

export function CareList({ label, children }: { label: string; children: React.ReactNode }) {
  return <section aria-label={label} className="divide-y divide-(--iux-border) rounded-lg border border-(--iux-border) bg-(--iux-card)">{children}</section>;
}
