import type { Metadata } from "next";
import Link from "next/link";
import { ConsoleHeader } from "@/components/console-header";
import { SiteFooter } from "@/components/site/footer";
import { PlanCards } from "@/components/site/plans";
import { BILLING_LIVE } from "@/lib/plans";

export const metadata: Metadata = {
  title: "Pricing · CodeIntent",
  description:
    "Free for open-source repositories. Every plan is free while CodeIntent is in beta.",
};

const QUESTIONS: [string, React.ReactNode][] = [
  [
    "What counts as a repository?",
    "Any repository you select when you install the GitHub App. Add or remove them on GitHub at any time.",
  ],
  [
    "Does CodeIntent run my code?",
    <>
      No. Both releases and your code are read statically; nothing is installed,
      imported or executed. <Link href="/docs/security">Security and data</Link>
    </>,
  ],
  [
    "What happens when the beta ends?",
    "Public repositories stay free. You will be asked to choose a plan before anything is charged.",
  ],
];

export default function Pricing() {
  return (
    <div className="ci ci-page">
      <ConsoleHeader current="pricing" />
      <main className="ci-main" id="main">
        <div className="ci-head">
          <div>
            <h1 className="ci-title">Pricing</h1>
            <p className="ci-intro">
              Free for open source. Private repositories and AI agents on Team.
            </p>
          </div>
        </div>
        {!BILLING_LIVE && (
          <p className="ci-notice" role="status">
            Every plan is free while CodeIntent is in beta. Prices below apply
            after it.
          </p>
        )}
        <PlanCards />
        <section className="ci-faq" aria-labelledby="faq">
          <h2 id="faq">Questions</h2>
          <dl>
            {QUESTIONS.map(([q, a]) => (
              <div key={q}>
                <dt>{q}</dt>
                <dd>{a}</dd>
              </div>
            ))}
          </dl>
        </section>
      </main>
      <SiteFooter />
    </div>
  );
}
