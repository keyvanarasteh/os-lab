# Dashboard translation review

The dashboard and desktop launcher support English (default), Turkish, German,
French, Spanish, Italian, Persian, and Arabic. UI dictionaries in
`src/i18n/generated/` contain machine translated English copy. They make the
whole dashboard usable in each language, but are **draft translations** until a
native speaker checks the wording and technical vocabulary.

## Review queue

- [ ] Review each generated dictionary (`tr`, `de`, `fr`, `es`, `it`, `fa`, `ar`)
  with native speakers, especially security terms, product names, units,
  command examples, and accessibility labels. Keep file paths, commands,
  product names, and placeholders exact.
- [ ] Translate the Markdown articles in `docs/legal/`, `docs/CONTENT.md`, and `CONTRIBUTING.md`
  with legal and maintainer review. They are currently marked as English in
  localized pages; surrounding navigation and controls are translated.
- [ ] Review authored company descriptions and project catalog content.
  Some source records mix English and Turkish, and exact-string UI translation
  only covers English phrases currently in the dictionaries.
- [ ] Localize variable text produced by console/backend responses and desktop
  native errors. Keep diagnostic commands and raw logs intact.
- [ ] Review Persian and Arabic layout, punctuation, number formatting, and
  mixed left-to-right technical text with native speakers.
- [x] Add a catalog parity check and a TSX source-string gap check in CI, with a documented
  workflow for new copy. The baseline records 97 pre-existing gaps for review; native review
  remains open. Astro templates and backend strings still need manual review.

## Adding UI copy

1. Add the English text in the component. Add the exact English phrase as a key in each
   `src/i18n/generated/*.json` dictionary, with a draft translation when a reviewer is not
   available. Preserve commands, file paths, product names and interpolation tokens.
2. Run `npm run test:i18n`, `npm run build` and `npm run test:e2e`. The CI parity check fails when
   a key is missing from any locale or new visible TSX copy lacks a catalog key. The browser tests
   exercise the content and Health pages. Update the source-gap baseline only after reviewing an
   intentional English-only phrase.
3. Inspect the new copy in English and Turkish. Request native review for the other locales and
   record unresolved wording or RTL issues in the queue above.

The Firewall Lab has its own detailed [translation checklist](../firewall-lab/TRANSLATION_TODO.md).
