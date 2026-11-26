/**
 * Shared update state between the layout's update modal and the top bar's update button, so the
 * check, the download and the close-for-update flow are reachable from every page.
 */
import { useSyncExternalStore } from "react";
import type { AppUpdateState, ContentState } from "../lib/api";

export interface UpdateSnapshot { app: AppUpdateState | null; content: ContentState | null }

let snapshot: UpdateSnapshot = { app: null, content: null };
const listeners = new Set<() => void>();

export function setUpdateSnapshot(next: UpdateSnapshot) {
  snapshot = next;
  listeners.forEach((listener) => listener());
}

export function useUpdateSnapshot(): UpdateSnapshot {
  return useSyncExternalStore(
    (listener) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
    () => snapshot,
    () => snapshot
  );
}

export const OPEN_UPDATES = "oslab:open-updates";

/** Open the update modal from anywhere; `check` asks the feeds again even when the last check is fresh. */
export function openUpdates(check = true) {
  window.dispatchEvent(new CustomEvent(OPEN_UPDATES, { detail: { check } }));
}

/** An offered app update the desktop app can install. */
export const appOffered = (s: AppUpdateState | null) => (s?.supported && !s.offline && s.updateAvailable ? s : null);
