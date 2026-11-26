/**
 * /firewall/device/?id= — one deployed firewall: quoted specs, why it was chosen, the branch it protects,
 * the alternatives compared and its rule set. One static page serves every id, including companies that
 * arrive later in a downloaded content pack.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ArrowLeftIcon, ArrowRightIcon, FireIcon } from "@phosphor-icons/react";
import { AppShell } from "../shell/app-shell";
import { TopBar } from "../shell/top-bar";
import { Badge, Empty, Section, Skeleton } from "../components/ui";
import { COMPANIES } from "../firewall/companies.generated";
import { liveCompanies } from "../firewall/live";
import { branchRole, copy, firewallPath, numberLocale, type FirewallLocale } from "../firewall/locale";
import { FirewallLanguageSwitch } from "../firewall/language-switch";
import { listDevices, readFilters, writeFilters } from "../firewall/devices";
import { devicesCopy } from "../firewall/devices-copy";
import type { Company } from "../firewall/types";
import { RuleRow } from "./firewall-page";
import { deviceHref } from "./firewall-devices-page";

/** The companies in force, or null until the console has said whether it has newer ones than the seed. */
function useSettledCompanies(): Company[] | null {
  const [companies, setCompanies] = useState<Company[] | null>(null);
  useEffect(() => {
    let alive = true;
    void liveCompanies().then((live) => alive && setCompanies(live ?? COMPANIES));
    return () => { alive = false; };
  }, []);
  return companies;
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2 text-sm">
      <dt className="text-(--iux-muted-foreground)">{label}</dt>
      <dd className="min-w-0 break-words text-end font-medium" dir="auto">{children}</dd>
    </div>
  );
}

export function FirewallDevicePage({ locale = "en" }: { locale?: FirewallLocale }) {
  const t = devicesCopy[locale];
  const companies = useSettledCompanies();
  const devices = useMemo(() => (companies ? listDevices(companies) : null), [companies]);
  const id = new URLSearchParams(window.location.search).get("id") ?? "";
  // The list's filters ride along, so going back keeps them.
  const filters = writeFilters(readFilters(window.location.search));
  const listHref = `${firewallPath(locale, "devices")}${filters ? `?${filters}` : ""}`;
  const device = devices?.find((item) => item.id === id);
  const number = (value: number) => value.toLocaleString(numberLocale(locale));
  const gbps = (value?: number) => (value == null ? t.notQuoted : <span dir="ltr">{number(value)} Gbps</span>);
  const usd = (value?: number) => (value == null ? t.notQuoted : <span dir="ltr">${number(value)}</span>);
  const elsewhere = device ? devices!.filter((item) => item.productKey === device.productKey && item.id !== device.id) : [];
  useEffect(() => { if (device) document.title = `${device.firewall.chosen.product} · ${copy[locale].lab} · os-lab`; }, [device?.id, locale]);

  return (
    <AppShell activeId="firewall-devices">
      <div className="iux min-h-screen">
        <TopBar title={device?.firewall.chosen.product ?? t.title} icon={<FireIcon size={20} weight="duotone" />} locale={locale} />
        <main className="mx-auto flex max-w-5xl flex-col gap-5 px-4 py-8 sm:px-6">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <a href={listHref} className="iux-touch-target inline-flex items-center gap-1.5 text-xs text-(--iux-muted-foreground) hover:text-[#f36c21]">
              <ArrowLeftIcon size={13} className="rtl:rotate-180" /> {t.back}
            </a>
            <FirewallLanguageSwitch locale={locale} slug="device" query={window.location.search} />
          </div>

          {!devices ? <Skeleton rows={4} /> : !device ? <Empty>{t.notFound}</Empty> : <>
            <header>
              <div className="flex flex-wrap items-center gap-2">
                <Badge>{device.firewall.segment}</Badge>
                <Badge tone={device.category === "waf" ? "warning" : undefined}>{device.category === "waf" ? t.waf : t.networkFirewall}</Badge>
                {device.ha ? <Badge>{t.haPair}</Badge> : null}
                {device.openSource ? <Badge tone="success">{t.openSource}</Badge> : null}
              </div>
              <h1 className="mt-2 break-words text-2xl font-bold tracking-tight" translate="no" dir="auto">{device.firewall.chosen.product}</h1>
              <p className="mt-1 text-sm text-(--iux-muted-foreground)" translate="no" dir="auto">{device.vendor}</p>
            </header>

            <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {([[t.throughput, gbps(device.firewall.chosen.throughputGbps)], [t.price, usd(device.firewall.chosen.priceUsd)],
                [copy[locale].rules, number(device.firewall.rules.length)],
                [t.connection, <span dir="ltr">{number(device.branch.bandwidth.downMbps)} / {number(device.branch.bandwidth.upMbps)} Mbps</span>]] as [string, ReactNode][])
                .map(([label, value]) => (
                  <div key={label} className="rounded-lg border border-(--iux-border) bg-(--iux-card) px-3 py-2">
                    <dd className="text-lg font-bold tabular-nums leading-tight">{value}</dd>
                    <dt className="text-[11px] uppercase tracking-wide text-(--iux-muted-foreground)">{label}</dt>
                  </div>
                ))}
            </dl>
            <p className="text-xs text-(--iux-muted-foreground)">{t.caveat}</p>

            <div className="grid items-start gap-4 md:grid-cols-2">
              <Section title={t.why}>
                <p className="break-words text-sm" dir="auto">{device.firewall.chosen.reason || t.noReason}</p>
              </Section>
              <Section title={t.deployment}>
                <dl className="divide-y divide-(--iux-border)">
                  <Fact label={t.company}><a className="text-[#f36c21] hover:underline" href={firewallPath(locale, device.company.slug)}>{device.company.name}</a></Fact>
                  <Fact label={t.branch}>{device.branch.name} · {branchRole(device.branch.role, locale)}</Fact>
                  <Fact label={t.location}>{device.branch.location}</Fact>
                  <Fact label={t.people}>{number(Object.values(device.branch.population ?? {}).reduce<number>((sum, value) => sum + (value ?? 0), 0))}</Fact>
                  <Fact label={t.subnet}><code dir="ltr">{device.branch.network.cidr}</code></Fact>
                  <Fact label={t.dmz}>{device.branch.network.dmz ? t.yes : t.no}</Fact>
                  <Fact label={t.drivers}>{(device.branch.bandwidth.drivers ?? []).join(" · ")}</Fact>
                </dl>
              </Section>
            </div>

            <Section title={t.vlans}>
              <div className="flex flex-wrap gap-1.5">
                {(device.branch.network.vlans ?? []).map((vlan) => (
                  <span key={vlan.id} title={vlan.note} dir="ltr" className="rounded-md border border-(--iux-border) px-2 py-0.5 font-mono text-[11px]">
                    {vlan.id} {vlan.name} · {vlan.cidr}
                  </span>
                ))}
              </div>
            </Section>

            <Section title={t.alternatives}>
              {device.firewall.alternatives.length ? <ul className="divide-y divide-(--iux-border)">
                {device.firewall.alternatives.map((item, index) => (
                  <li key={index} className="py-2.5 text-sm">
                    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                      <strong className="min-w-0 break-words font-medium" translate="no" dir="auto">{item.product}</strong>
                      <span className="text-xs text-(--iux-muted-foreground)" translate="no">{item.vendor}</span>
                      <span className="ms-auto text-xs tabular-nums">{gbps(item.throughputGbps)} · {usd(item.priceUsd)}</span>
                    </div>
                    {item.reason ? <p className="mt-1 break-words text-xs text-(--iux-muted-foreground)" dir="auto">{item.reason}</p> : null}
                  </li>
                ))}
              </ul> : <Empty>{t.noAlternatives}</Empty>}
            </Section>

            <Section title={t.rules}>
              <ol className="divide-y divide-(--iux-border)">
                {device.firewall.rules.map((rule, index) => <RuleRow key={index} rule={rule} locale={locale} />)}
              </ol>
            </Section>

            <Section title={t.elsewhere}>
              {elsewhere.length ? <ul className="divide-y divide-(--iux-border)">
                {elsewhere.map((item) => (
                  <li key={item.id}>
                    <a href={deviceHref(locale, item.id, filters)} className="iux-touch-target flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm hover:text-[#f36c21]">
                      <span className="min-w-0 break-words" dir="auto">{item.company.name} · {item.branch.name} · {item.firewall.segment}</span>
                      <ArrowRightIcon size={13} className="ms-auto rtl:rotate-180" />
                    </a>
                  </li>
                ))}
              </ul> : <Empty>{t.noElsewhere}</Empty>}
            </Section>
          </>}
        </main>
      </div>
    </AppShell>
  );
}
