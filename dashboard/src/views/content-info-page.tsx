/** /content/ — how signed content updates work and how to prove a contribution; rendered from docs/CONTENT.md. */
import { ArrowsClockwiseIcon } from "@phosphor-icons/react";
import { AppShell } from "../shell/app-shell";
import { TopBar } from "../shell/top-bar";
import { REPO_BLOB } from "../lib/legal";

export function ContentInfoPage({ html }: { html: string }) {
  return (
    <AppShell activeId="content">
      <div className="iux min-h-screen">
        <TopBar title="Content updates" icon={<ArrowsClockwiseIcon size={20} weight="duotone" />} />
        <main className="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-8 sm:px-6">
          {/* Our own Markdown from docs/CONTENT.md, compiled at build time */}
          <article className="legal-doc" lang="en" translate="no" dangerouslySetInnerHTML={{ __html: html }} />
          <p className="border-t border-(--iux-border) pt-4 text-xs text-(--iux-muted-foreground)">
            Source:{" "}
            <a className="underline" href={`${REPO_BLOB}/docs/CONTENT.md`} target="_blank" rel="noreferrer">
              docs/CONTENT.md
            </a>
            . The same text ships with the repository; its history is the change log.
          </p>
        </main>
      </div>
    </AppShell>
  );
}
