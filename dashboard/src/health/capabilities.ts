/** Types for the capability catalog supplied by /api/capabilities. Lab support is calculated by console/oslab.py. */
import type { LabId } from "../lib/api";

export type PlatformId = "windows" | "macos" | "linux";
export type Level = "full" | "partial" | "none";

export interface Support {
  level: Level;
  note: string;
}

export interface Capability {
  id: string;
  title: string;
  summary: string;
  lab?: LabId;
  support: Record<PlatformId, Support>;
  children?: Array<{ id: string; title: string; support: Record<PlatformId, Support> }>;
}

export interface CapabilityGroup {
  id: string;
  title: string;
  description: string;
  items: Capability[];
}

export interface CapabilityCatalog {
  platforms: Array<{ id: PlatformId; label: string; installer: string; engine: string }>;
  groups: CapabilityGroup[];
}

export const LEVEL_LABEL: Record<Level, string> = { full: "Supported", partial: "Needs setup", none: "Not available" };

export function hostPlatform(os: string | undefined): PlatformId | null {
  return os === "windows" || os === "macos" || os === "linux" ? os : null;
}

export interface PlatformSummary {
  full: number;
  partial: number;
  none: number;
}

export function summarize(groups: CapabilityGroup[], platform: PlatformId): PlatformSummary {
  const out: PlatformSummary = { full: 0, partial: 0, none: 0 };
  for (const group of groups) for (const item of group.items) out[item.support[platform].level]++;
  return out;
}
