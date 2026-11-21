import "@/app/landing.css";
import { Advisories } from "./advisories";
import { BacktestSection } from "./backtest";
import { readBacktest } from "./backtest-data";
import { Closing, SiteFooter } from "./closing";
import { CommentSection } from "./pr-comment";
import { EarlyWarning } from "./early-warning";
import { Hero } from "./hero";
import { HowItWorks } from "./how-it-works";
import { Reveal } from "./reveal";
import { Security } from "./security";
import { SiteHeader } from "./site-header";
import { Surfaces } from "./surfaces";
import { Upstream } from "./upstream";
import { Verdicts } from "./verdicts";

export default async function LandingPage() {
  const backtest = await readBacktest();
  return (
    <div className="lp">
      <a className="lp-skip" href="#main">
        Skip to content
      </a>
      <SiteHeader />
      <main id="main">
        <Hero />
        <CommentSection />
        <HowItWorks />
        <Verdicts />
        <Upstream />
        <EarlyWarning />
        <Advisories />
        <Surfaces />
        <BacktestSection data={backtest} />
        <Security />
        <Closing />
      </main>
      <SiteFooter />
      <Reveal />
    </div>
  );
}
