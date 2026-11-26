/**
 * Sticky page top bar, ported from qLar's apk-lab/apk-lab-top-bar.tsx: menu/search on small
 * screens, the orange shield, an optional back crumb, the title, live lab state and the theme toggle.
 */
import type { ReactNode } from "react";
import { ArrowCircleUpIcon, ArrowLeftIcon, CircleIcon, ShieldCheckIcon } from "@phosphor-icons/react";
import { appOffered, openUpdates, useUpdateSnapshot } from "../views/update-store";
import { ShellMenuButton, ThemeToggle } from "./app-shell";
import { androidLogsStore, healthStore, jobsStore } from "../lib/api";
import { copy, FIREWALL_LOCALES, firewallLanguageName, statusCopy, type FirewallLocale } from "../firewall/locale";
import { localeFromPath, localePath } from "../i18n/paths";

export interface TopBarProps {
  title: string;
  back?: { href: string; label: string };
  icon?: ReactNode;
  locale?: FirewallLocale;
}

/**
 * Updates on every page: opens the layout's update center and checks again. A dot marks a waiting
 * update; while the installer downloads it shows the percentage.
 */
function UpdateButton() {
  const { app, content } = useUpdateSnapshot();
  const install = app?.install;
  const downloading = install?.phase === "downloading";
  const percent = downloading && install?.total ? Math.round(((install.received ?? 0) / install.total) * 100) : null;
  const waiting = Boolean(appOffered(app) || (content && !content.offline && content.latest && content.latest.sequence > content.sequence));
  const label = downloading ? "Downloading update" : install?.phase === "done" ? "Update ready to install" : waiting ? "Update available" : "Check for updates";
  return (
    <button type="button" className="iux-btn relative" data-variant="outline" data-size="icon" aria-label={label} title={label}
      onClick={() => openUpdates(!downloading && install?.phase !== "done")}>
      <ArrowCircleUpIcon size={16} className={downloading ? "animate-pulse text-[#f36c21]" : undefined} />
      {percent !== null ? <span className="absolute -right-1 -bottom-1 rounded bg-[#f36c21] px-0.5 text-[9px] leading-tight text-white tabular-nums" dir="ltr">{percent}%</span>
        : waiting || install?.phase === "done" ? <span className="absolute -top-0.5 -right-0.5 size-2 rounded-full bg-[#f36c21]" aria-hidden="true" /> : null}
    </button>
  );
}

export function TopBar({ title, back, icon, locale }: TopBarProps) {
  const publicPages = import.meta.env.PUBLIC_SITE_MODE === "pages";
  const currentLocale = locale ?? (typeof window === "undefined" ? "en" : localeFromPath(window.location.pathname));
  const { data: health, error } = healthStore.use();
  const { data: jobs } = jobsStore.use();
  const { data: logs } = androidLogsStore.use();
  const busy = Boolean(logs?.running) || (jobs ?? []).some((j) => j.state === "running");
  const online = health?.status === "ok" && !error;
  const t = statusCopy[currentLocale];
  const label = !online
    ? (error ? t.offline : t.connecting)
    : busy ? t.running : t.active;
  return (
    <header className="sticky top-0 z-20 border-b border-(--iux-border) bg-(--iux-background)/80 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-4 sm:px-6">
        <ShellMenuButton />
        <span className="shrink-0 text-[#f36c21]">{icon ?? <ShieldCheckIcon size={20} weight="duotone" />}</span>
        {back ? (
          <>
            <a
              href={localePath(back.href, currentLocale)}
              className="hidden shrink-0 items-center gap-1 text-xs text-(--iux-muted-foreground) hover:text-(--iux-foreground) sm:flex"
            >
              <ArrowLeftIcon size={12} /> {back.label}
            </a>
            <span className="hidden text-(--iux-muted-foreground) sm:inline">/</span>
          </>
        ) : null}
        <h1 className="min-w-0 truncate text-base font-semibold">{title}</h1>
        <div className="ml-auto flex items-center gap-3">
          <select
            aria-label={copy[currentLocale].language}
            value={currentLocale}
            onChange={(event) => {
              const path = localePath(window.location.pathname, event.target.value as FirewallLocale);
              window.location.assign(`${path}${window.location.search}${window.location.hash}`);
            }}
            className="max-w-25 rounded-md border border-(--iux-border) bg-(--iux-background) px-1.5 py-1 text-xs"
            dir="ltr"
          >
            {FIREWALL_LOCALES.map((code) => <option key={code} value={code}>{firewallLanguageName[code]}</option>)}
          </select>
          {!publicPages ? <div className="flex items-center gap-1.5 text-xs text-(--iux-muted-foreground)">
            <CircleIcon
              size={8}
              weight="fill"
              className={!online ? "text-zinc-500" : busy ? "animate-pulse text-[#f36c21]" : "text-[#00d084]"}
            />
            <span className="hidden sm:inline">{label}</span>
          </div> : null}
          {!publicPages ? <UpdateButton /> : null}
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
