# Firewall Lab translation TODO

The firewall dashboard and the desktop app support `en` (default), `tr`, `de`, `fr`, `es`, `it`, `fa`, and `ar`. The language switcher uses **DE** for German. English stays at `/firewall/`; other languages use `/<locale>/firewall/`. Persian and Arabic pages use right to left direction.

## Completed UI translations

- [x] Translate the Firewall Lab page, company view, navigation labels, rule terms, and status text for **DE, FR, ES, IT, FA, and AR**.
- [x] Translate the desktop launcher for all supported languages.
- [x] Translate the contribution dialog, gap audit controls, and impact dialog labels for all supported languages.

## Content and review still needed

- [ ] Review and correct the Turkish and new DE, FR, ES, IT, FA, and AR UI copy in `dashboard/src/firewall/locale.ts`, `dashboard/src/firewall/contribute-ui.ts`, `dashboard/src/firewall/audit-ui.ts`, and `app/ui/launcher.js` with native speakers.
- [ ] Move the lesson-specific gap finding text in `dashboard/src/firewall/audit.ts` and impact scenario text in `dashboard/src/firewall/impact.ts` into locale dictionaries and translate it. The finding titles, evidence, fixes, scenarios, and costs still appear in English in every locale.
- [ ] Translate shared shell navigation, search, and theme labels in `dashboard/src/shell/` for all supported locales. Firewall navigation and top bar status are translated; other shell sections remain in English.
- [ ] Decide how to localize student authored company content (`firewall-lab/companies/*/company.json`), including company summaries, branch names, notes, reasons, monitoring, and CVE notes. The UI intentionally displays each submission in its source language until translations are supplied.
- [ ] Review plural forms, number formatting, and right to left layout with native speakers, especially Arabic and Persian. Keep technical identifiers such as VLAN, CIDR, CVE, product names, and URLs readable.
- [ ] Add native speaker review and update the language switcher labels when translated copy is ready.

The main Firewall Lab interface is translated. Lesson findings and student authored company data need separate content translation, and native speaker review is still recommended.
