import type { Metadata } from "next";
import Link from "next/link";
import { ConsoleHeader } from "@/components/console-header";
import { SiteFooter } from "@/components/site/footer";
import { ArrowOut, ArrowRight, GitHubMark } from "@/components/site/icons";
import { DEMO_PR } from "@/components/site/links";
import { HeroStage } from "@/components/home/hero-stage";
import { AlertCard, CommentCard } from "@/components/home/examples";
import { installUrl } from "@/lib/auth";

const title = "CodeIntent: know what a dependency upgrade breaks";
const description =
  "A GitHub App for Python repositories. On every dependency pull request it names the line in your code that breaks, what to use instead, and why upstream changed it.";

export const metadata: Metadata = {
  title,
  description,
  openGraph: { title, description, siteName: "CodeIntent", type: "website" },
  twitter: { card: "summary", title, description },
};

export default function Home() {
  const install = installUrl();
  return (
    <div className="ci ci-home">
      <ConsoleHeader />
      <main id="main" className="ci-home-main">
        <section className="ci-hero" aria-labelledby="hero-title">
          <div className="ci-hero-copy">
            <h1 id="hero-title" className="ci-display">
              <span>Know what breaks</span> <span>before you merge.</span>
            </h1>
            <p className="ci-lede">
              A GitHub App for Python repositories. On every dependency pull
              request it names the line that breaks, what to use instead, and
              why upstream changed it.
            </p>
            <a className="ci-btn" href={install}>
              <GitHubMark />
              Install on GitHub
            </a>
          </div>
          <HeroStage>
            <CommentCard />
            <AlertCard />
          </HeroStage>
        </section>
        <section className="ci-steps" aria-labelledby="steps-title">
          <h2 id="steps-title" className="sr-only">
            Three steps
          </h2>
          <ol>
            <li>
              <span className="ci-num" aria-hidden="true">
                1
              </span>
              <div>
                <h3>Install on GitHub</h3>
                <p>Pick the repositories it may read.</p>
              </div>
              <a className="ci-step-link" href={install}>
                Install <ArrowOut />
              </a>
            </li>
            <li>
              <span className="ci-num" aria-hidden="true">
                2
              </span>
              <div>
                <h3>Connect your Telegram group</h3>
                <p>Alerts when an upgrade breaks you.</p>
              </div>
              <Link className="ci-step-link" href="/setup#telegram">
                Connect <ArrowRight />
              </Link>
            </li>
            <li>
              <span className="ci-num" aria-hidden="true">
                3
              </span>
              <div>
                <h3>Runs on every dependency PR</h3>
                <p>One check, one comment. Automatic.</p>
              </div>
              <a className="ci-step-link" href={DEMO_PR}>
                See a real one <ArrowOut />
              </a>
            </li>
          </ol>
        </section>
      </main>
      <SiteFooter />
    </div>
  );
}
