# Brand

os-lab uses the QS-Lab identity: an angular Q drawn in Ink `#171C24` with one Signal `#4EA8FF` bar, built in the iQ family.

## Masters

[[docs/brand/qs-lab]] holds the design files: Q Core (the primary mark), the Q Prompt and QS Grid alternates, horizontal lockups, the app tile and the concepts board.

Each mark has light, dark and mono SVG masters with 1024-pixel PNG exports; [[docs/brand/qs-lab/qs-lab-concepts.svg]] shows them side by side. The same set is registered in iUX as the os-lab brand.

## Where the mark appears

The app tile is the single source for every icon the product ships, so the desktop app, launcher and dashboard show the same mark.

- [[app/icon.svg]] is the app tile; `npm run icons` in `app/` regenerates the Tauri bundle icons in [[app/src-tauri/icons]] from it.
- [[app/ui/index.html]] inlines the tile on the launcher page.
- [[dashboard/public/favicon.svg]] is the same tile, used as the favicon and as the sidebar logo in the dashboard shell; the committed `dashboard/dist` copy matches it.

The dashboard's orange UI accent is separate from the brand mark and is unchanged.
