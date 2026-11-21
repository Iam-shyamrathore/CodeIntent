import { ConsoleHeader } from "@/components/console-header";
import { DocsNav, DocsPager } from "@/components/docs/docs-nav";
import { SiteFooter } from "@/components/site/footer";

export default function DocsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="ci ci-page">
      <ConsoleHeader current="docs" />
      <div className="ci-app ci-docs">
        <DocsNav />
        <main className="ci-app-main" id="main">
          <article className="ci-prose">{children}</article>
          <DocsPager />
        </main>
      </div>
      <SiteFooter />
    </div>
  );
}
