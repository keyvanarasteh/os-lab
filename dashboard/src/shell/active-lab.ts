/**
 * The lab the sidebar focuses on. Picking a lab in the switcher (⌘L / Ctrl+L) narrows the OS Lab
 * group to that lab alone; "All labs" restores the full list. The choice is remembered in
 * localStorage, and a lab page reached through a link, Spotlight or a bookmark re-focuses the nav.
 */
import { useCallback, useEffect, useState } from "react";
import type { LabId } from "../lib/api";

/** The cleanup lab has no engine status of its own but is a sidebar lab like the others. */
export type ActiveLabId = LabId | "cleanup";

const KEY = "oslab.sidebar.activeLab";

export function readActiveLab(): ActiveLabId | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw === null ? null : (JSON.parse(raw) as ActiveLabId | null);
  } catch {
    return null;
  }
}

export function writeActiveLab(lab: ActiveLabId | null) {
  try {
    if (lab === null) window.localStorage.removeItem(KEY);
    else window.localStorage.setItem(KEY, JSON.stringify(lab));
  } catch {
    // Storage unavailable: the focus lasts for this page view
  }
}

/** The lab a sidebar section belongs to, so a direct link or Spotlight pick focuses the nav there. */
export function labOfSection(activeId: string): ActiveLabId | null {
  if (activeId.startsWith("lab-")) return activeId.slice(4) as ActiveLabId;
  if (activeId === "android" || activeId.startsWith("android-")) return "android";
  if (activeId.startsWith("source-")) return "source";
  if (activeId.startsWith("cleanup-")) return "cleanup";
  if (activeId === "web-lab") return "web";
  return null;
}

/**
 * The focused lab: the page's own lab when there is one, else the remembered choice.
 * The pages render only in the browser, so storage can be read up front.
 */
export function useActiveLab(activeId: string): [ActiveLabId | null, (lab: ActiveLabId | null) => void] {
  const [lab, setLab] = useState<ActiveLabId | null>(() => labOfSection(activeId) ?? readActiveLab());
  // A lab page reached through anything but the switcher still re-focuses the sidebar there.
  useEffect(() => {
    const focus = labOfSection(activeId);
    if (focus) writeActiveLab(focus);
  }, [activeId]);
  const choose = useCallback((next: ActiveLabId | null) => {
    setLab(next);
    writeActiveLab(next);
  }, []);
  return [lab, choose];
}
