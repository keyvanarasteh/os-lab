import { copy, FIREWALL_LOCALES, firewallLanguageName, firewallPath, type FirewallLocale } from "./locale";

export function FirewallLanguageSwitch({ locale, slug }: { locale: FirewallLocale; slug?: string }) {
  return (
    <nav aria-label={copy[locale].language} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs font-semibold" dir="ltr">
      {FIREWALL_LOCALES.map((target) => (
        <a
          key={target}
          href={firewallPath(target, slug)}
          lang={target}
          title={firewallLanguageName[target]}
          aria-label={firewallLanguageName[target]}
          aria-current={locale === target ? "page" : undefined}
          className={locale === target ? "text-[#f36c21]" : "text-(--iux-muted-foreground) hover:underline"}
        >{target.toUpperCase()}</a>
      ))}
    </nav>
  );
}
