/**
 * One icon and tint per catalog group, shared by the sidebar, the scan plan rows and a group's own
 * page, so "Homebrew" or "Xcode & Apple" reads the same everywhere.
 */
import type { ReactNode } from "react";
import {
  AppleLogoIcon, AppWindowIcon, BeerSteinIcon, CloudIcon, CodeIcon, CoffeeIcon, CpuIcon, DotsThreeIcon,
  FileJsIcon, FilePyIcon, GlobeIcon, HardDrivesIcon, RobotIcon, type Icon
} from "@phosphor-icons/react";

const ICONS: Record<string, { icon: Icon; color: string }> = {
  apple: { icon: AppleLogoIcon, color: "#3ba7e5" },
  javascript: { icon: FileJsIcon, color: "#e2b93b" },
  python: { icon: FilePyIcon, color: "#4f8fd6" },
  jvm: { icon: CoffeeIcon, color: "#d9822b" },
  native: { icon: CpuIcon, color: "#c8653a" },
  cloud: { icon: CloudIcon, color: "#5aa9a0" },
  editors: { icon: CodeIcon, color: "#4a90e2" },
  agents: { icon: RobotIcon, color: "#9b6bdf" },
  homebrew: { icon: BeerSteinIcon, color: "#2fb59a" },
  apps: { icon: AppWindowIcon, color: "#e0567a" },
  browsers: { icon: GlobeIcon, color: "#3f9fd8" },
  system: { icon: HardDrivesIcon, color: "#a86ae0" },
  other: { icon: DotsThreeIcon, color: "#8a8a85" }
};

/** The bare glyph in the group's colour, sized for the sidebar. */
export function GroupGlyph({ groupId, size = 16 }: { groupId: string; size?: number }): ReactNode {
  const { icon: Glyph, color } = ICONS[groupId] ?? ICONS.other!;
  return <Glyph size={size} weight="duotone" color={color} aria-hidden="true" />;
}

/** The glyph on a tinted rounded tile, for plan rows and page headers. */
export function GroupTile({ groupId, size = 32 }: { groupId: string; size?: number }) {
  const { icon: Glyph, color } = ICONS[groupId] ?? ICONS.other!;
  return <span aria-hidden="true" className="grid shrink-0 place-items-center rounded-lg"
    style={{ width: size, height: size, background: `${color}22`, border: `1px solid ${color}33` }}>
    <Glyph size={Math.round(size * 0.56)} weight="duotone" color={color} />
  </span>;
}

/** Measured bytes per catalog group from the latest scan, shared with the sidebar badges. */
export const GROUP_BYTES_KEY = "oslab.cleanup.groupBytes";
export const GROUP_BYTES_EVENT = "oslab:cleanup-group-bytes";

export function publishGroupBytes(bytes: Record<string, number>) {
  try { window.localStorage.setItem(GROUP_BYTES_KEY, JSON.stringify(bytes)); } catch { /* storage may be blocked */ }
  window.dispatchEvent(new CustomEvent(GROUP_BYTES_EVENT, { detail: bytes }));
}

export function readGroupBytes(): Record<string, number> {
  try {
    const value = JSON.parse(window.localStorage.getItem(GROUP_BYTES_KEY) ?? "{}");
    return value && typeof value === "object" ? value as Record<string, number> : {};
  } catch { return {}; }
}
