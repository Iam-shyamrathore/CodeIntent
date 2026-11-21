import { OSV } from "./links";

const BEFORE = [
  {
    id: "GHSA-9wx4-h78v-vm56",
    href: "https://github.com/advisories/GHSA-9wx4-h78v-vm56",
    fixed: "2.32.0",
  },
  {
    id: "GHSA-9hjg-9r4m-mvj7",
    href: "https://github.com/advisories/GHSA-9hjg-9r4m-mvj7",
    fixed: "2.32.4",
  },
  {
    id: "GHSA-gc5v-m9x4-r6x2",
    href: "https://github.com/psf/requests/security/advisories/GHSA-gc5v-m9x4-r6x2",
    fixed: "2.33.0",
  },
];

export function Advisories() {
  return (
    <section
      className="lp-section lp-advisories"
      aria-labelledby="advisories-title"
    >
      <div className="lp-wrap lp-split lp-split-reverse">
        <div className="lp-section-head" data-reveal>
          <p className="lp-index">§ 06 — Advisories</p>
          <h2 id="advisories-title">
            Known vulnerabilities, for the version you leave and the one you
            take.
          </h2>
          <p className="lp-lede">
            Every comment looks up both versions on <a href={OSV}>OSV.dev</a>,
            so an upgrade that fixes advisories says so, and one that introduces
            them cannot hide behind a clean API comparison. Withdrawn advisories
            are left out.
          </p>
        </div>
        <div className="lp-bezel lp-adv" data-reveal>
          <div className="lp-bezel-core">
            <p className="lp-adv-title">
              <b>
                <code>requests</code> 2.31.0 → 2.34.2
              </b>
              <span>codeintent-demo #2</span>
            </p>
            <div className="lp-adv-cols">
              <div>
                <p className="lp-adv-version">2.31.0 · you leave</p>
                <ul>
                  {BEFORE.map((item) => (
                    <li key={item.id}>
                      <a href={item.href}>
                        <code>{item.id}</code>
                      </a>
                      <span>fixed in {item.fixed}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="lp-adv-version">2.34.2 · you take</p>
                <p className="lp-adv-none">No known advisories</p>
              </div>
            </div>
            <p className="lp-adv-foot">
              Verdict: No known impact. Compared 1 of 4 uses; 3 could not be
              followed, but touch nothing this upgrade changed.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
