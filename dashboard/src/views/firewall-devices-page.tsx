/**
 * /firewall/devices/ — search, filter and list every deployed firewall; each opens /firewall/device/?id=.
 * The filters live in the address bar, so a filtered list can be shared and survives a visit to a detail page.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ArrowLeftIcon, FireIcon, MagnifyingGlassIcon } from "@phosphor-icons/react";
import { AppShell } from "../shell/app-shell";
import { TopBar } from "../shell/top-bar";
import { Badge, Empty } from "../components/ui";
import { useLiveCompanies } from "../firewall/live";
import { branchRole, copy, firewallPath, numberLocale, type FirewallLocale } from "../firewall/locale";
import { FirewallLanguageSwitch } from "../firewall/language-switch";
import {
  filterDevices, listDevices, matchedAlternative, NO_FILTERS, readFilters, SORTS, writeFilters,
  type DeviceFilters, type DeviceSort, type FirewallDevice
} from "../firewall/devices";
import { devicesCopy } from "../firewall/devices-copy";
import type { BranchRole } from "../firewall/types";

const SORT_LABEL = {
  company: "sortCompany", vendor: "sortVendor", product: "sortProduct", "price-asc": "sortPriceAsc",
  "price-desc": "sortPriceDesc", "throughput-desc": "sortThroughputDesc", "throughput-asc": "sortThroughputAsc"
} as const satisfies Record<DeviceSort, keyof (typeof devicesCopy)["en"]>;

const distinct = (values: string[]) => [...new Set(values)].sort((a, b) => a.localeCompare(b));

export const deviceHref = (locale: FirewallLocale, id: string, filters = "") =>
  `${firewallPath(locale, "device")}?id=${encodeURIComponent(id)}${filters ? `&${filters}` : ""}`;

function Control({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-xs font-medium text-(--iux-muted-foreground)">
      <span>{label}</span>
      {children}
    </label>
  );
}

function Row({ device, filters, locale }: { device: FirewallDevice; filters: DeviceFilters; locale: FirewallLocale }) {
  const t = devicesCopy[locale];
  const { chosen, segment } = device.firewall;
  const alternative = matchedAlternative(device, filters);
  const number = (value: number) => value.toLocaleString(numberLocale(locale));
  return (
    <li>
      <a href={deviceHref(locale, device.id, writeFilters(filters))}
        className="grid gap-x-4 gap-y-1 rounded-xl border border-(--iux-border) bg-(--iux-card) p-4 transition-colors hover:border-[#f36c21] sm:grid-cols-[minmax(0,1fr)_auto]">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <strong className="break-words text-sm font-semibold" translate="no" dir="auto">{chosen.product}</strong>
            <span className="text-xs text-(--iux-muted-foreground)" translate="no">{device.vendor}</span>
            <Badge>{segment}</Badge>
            {device.category === "waf" ? <Badge tone="warning">WAF</Badge> : null}
            {device.ha ? <Badge>{t.haPair}</Badge> : null}
          </div>
          <p className="mt-1 break-words text-xs text-(--iux-muted-foreground)" dir="auto">
            {device.company.name} · {device.branch.name} · {branchRole(device.branch.role, locale)} · {device.branch.location}
          </p>
          {alternative ? <p className="mt-1 text-xs text-[#f36c21]">{t.matchedAlternative} <span translate="no">{alternative.vendor} · {alternative.product}</span></p> : null}
        </div>
        <dl className="flex gap-4 text-xs sm:flex-col sm:items-end sm:gap-1">
          <div className="flex gap-1"><dt className="sr-only">{t.throughput}</dt><dd className="font-semibold tabular-nums">{chosen.throughputGbps == null ? <span className="font-normal text-(--iux-muted-foreground)">{t.throughput}: {t.notQuoted}</span> : <span dir="ltr">{number(chosen.throughputGbps)} Gbps</span>}</dd></div>
          <div className="flex gap-1"><dt className="sr-only">{t.price}</dt><dd className="tabular-nums">{chosen.priceUsd == null ? <span className="text-(--iux-muted-foreground)">{t.price}: {t.notQuoted}</span> : <span dir="ltr">${number(chosen.priceUsd)}</span>}</dd></div>
        </dl>
      </a>
    </li>
  );
}

export function FirewallDevicesPage({ locale = "en" }: { locale?: FirewallLocale }) {
  const t = devicesCopy[locale];
  const companies = useLiveCompanies();
  const devices = useMemo(() => listDevices(companies), [companies]);
  const [filters, setFilters] = useState<DeviceFilters>(() => readFilters(window.location.search));
  const set = <K extends keyof DeviceFilters>(key: K, value: DeviceFilters[K]) => setFilters((old) => ({ ...old, [key]: value }));
  const query = writeFilters(filters);
  useEffect(() => { history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}`); }, [query]);
  const found = useMemo(() => filterDevices(devices, filters), [devices, filters]);
  const vendors = useMemo(() => distinct(devices.map((d) => d.vendor)), [devices]);
  const segments = useMemo(() => distinct(devices.map((d) => d.firewall.segment)), [devices]);
  const roles = useMemo(() => distinct(devices.map((d) => d.branch.role)) as BranchRole[], [devices]);
  const names = useMemo(() => [...companies].sort((a, b) => a.name.localeCompare(b.name)), [companies]);
  const filtered = writeFilters({ ...filters, sort: NO_FILTERS.sort }) !== "";

  const select = (key: "vendor" | "segment" | "role" | "category" | "company", label: string, options: [string, string][]) => (
    <Control label={label}>
      <select className="iux-input w-full min-w-0" value={filters[key]} onChange={(event) => set(key, event.target.value as never)}>
        <option value="">{t.all}</option>
        {options.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
      </select>
    </Control>
  );
  const number = (key: "minGbps" | "maxPrice", label: string) => (
    <Control label={label}>
      <input type="number" min="0" step="any" inputMode="decimal" className="iux-input w-full min-w-0" value={filters[key]}
        onChange={(event) => set(key, event.target.value)} />
    </Control>
  );
  const check = (key: "openSource" | "alternatives", label: string) => (
    <label className="iux-touch-target inline-flex items-center gap-2 text-sm">
      <input type="checkbox" checked={filters[key] === "1"} onChange={(event) => set(key, event.target.checked ? "1" : "")} />
      <span>{label}</span>
    </label>
  );

  return (
    <AppShell activeId="firewall-devices">
      <div className="iux min-h-screen">
        <TopBar title={t.title} icon={<FireIcon size={20} weight="duotone" />} locale={locale} />
        <main className="mx-auto flex max-w-5xl flex-col gap-5 px-4 py-8 sm:px-6">
          <header>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <a href={firewallPath(locale)} className="iux-touch-target inline-flex items-center gap-1.5 text-xs text-(--iux-muted-foreground) hover:text-[#f36c21]">
                <ArrowLeftIcon size={13} className="rtl:rotate-180" /> {copy[locale].lab}
              </a>
              <FirewallLanguageSwitch locale={locale} slug="devices" />
            </div>
            <h1 className="mt-3 flex items-center gap-2 text-xl font-bold tracking-tight">
              <FireIcon size={22} className="text-[#f36c21]" weight="duotone" /> {t.title}
            </h1>
            <p className="mt-1.5 max-w-3xl text-sm text-(--iux-muted-foreground)">{t.intro}</p>
            <p className="mt-1 max-w-3xl text-xs text-(--iux-muted-foreground)">{t.caveat}</p>
          </header>

          <form role="search" className="flex flex-col gap-3 rounded-xl border border-(--iux-border) p-4" onSubmit={(event) => event.preventDefault()}>
            <Control label={t.search}>
              <span className="relative block">
                <MagnifyingGlassIcon size={15} className="pointer-events-none absolute start-2.5 top-1/2 -translate-y-1/2" aria-hidden="true" />
                <input type="search" className="iux-input w-full ps-8" placeholder={t.searchHint} value={filters.q}
                  onChange={(event) => set("q", event.target.value)} />
              </span>
            </Control>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              {select("vendor", t.vendor, vendors.map((v) => [v, v]))}
              {select("segment", t.segment, segments.map((s) => [s, s]))}
              {select("role", t.role, roles.map((r) => [r, branchRole(r, locale)]))}
              {select("category", t.category, [["firewall", t.networkFirewall], ["waf", t.waf]])}
              {select("company", t.company, names.map((c) => [c.slug, c.name]))}
              {number("minGbps", t.minGbps)}
              {number("maxPrice", t.maxPrice)}
              <Control label={t.sort}>
                <select className="iux-input w-full min-w-0" value={filters.sort} onChange={(event) => set("sort", event.target.value as DeviceSort)}>
                  {SORTS.map((sort) => <option key={sort} value={sort}>{t[SORT_LABEL[sort]]}</option>)}
                </select>
              </Control>
            </div>
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
              {check("openSource", t.openSourceOnly)}
              {check("alternatives", t.alternativesToo)}
              <button type="button" className="iux-btn ms-auto" data-variant="outline" disabled={!filtered}
                onClick={() => setFilters({ ...NO_FILTERS, sort: filters.sort })}>{t.clear}</button>
            </div>
          </form>

          <p role="status" className="text-xs text-(--iux-muted-foreground)">
            {t.shown.replace("{shown}", found.length.toLocaleString(numberLocale(locale))).replace("{total}", devices.length.toLocaleString(numberLocale(locale)))}
          </p>
          {found.length
            ? <ul className="flex flex-col gap-2">{found.map((device) => <Row key={device.id} device={device} filters={filters} locale={locale} />)}</ul>
            : <Empty>{t.none}</Empty>}
        </main>
      </div>
    </AppShell>
  );
}
