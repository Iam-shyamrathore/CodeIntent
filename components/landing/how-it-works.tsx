import { RigArt } from "./rig/art";

export function HowItWorks() {
  return (
    <section className="lp-section lp-how" id="how" aria-labelledby="how-title">
      <div className="lp-wrap">
        <div className="lp-section-head lp-section-head-split" data-reveal>
          <div>
            <p className="lp-index">§ 02 — How it works</p>
            <h2 id="how-title">
              Five stations, one direction. Nothing is run.
            </h2>
          </div>
          <p className="lp-lede">
            Each pull request passes the same bench in the same order. Every
            station reads files: the manifest, your source, the two published
            releases and the upstream history. The verdict at the end comes from
            fixed rules over what was read.
          </p>
        </div>
        <div data-reveal>
          <RigArt />
        </div>
      </div>
    </section>
  );
}
