import { HTTPX_2879, HTTPX_3319, HTTPX_QUOTE_COMMIT } from "./links";

const TRAIL = [
  {
    when: "encode/httpx#2879",
    href: HTTPX_2879,
    what: "proxies= is deprecated in favour of proxy= and mounts=.",
  },
  {
    when: "httpx 0.27.2",
    what: "The release warns at run time.",
    quote:
      "The 'proxies' argument is now deprecated. Use 'proxy' or 'mounts' instead.",
  },
  {
    when: "encode/httpx#3319",
    href: HTTPX_3319,
    what: (
      <>
        Introduce new <code>SSLContext</code> API &amp; escalate deprecations.
      </>
    ),
    quote: (
      <>
        The deprecated <code>proxies</code> argument has now been removed.
      </>
    ),
    source: HTTPX_QUOTE_COMMIT,
  },
  {
    when: "httpx 0.28.0",
    what: "Released 28 November 2024 without proxies=.",
  },
];

export function Upstream() {
  return (
    <section
      className="lp-section lp-upstream"
      aria-labelledby="upstream-title"
    >
      <div className="lp-wrap lp-split">
        <div className="lp-section-head" data-reveal>
          <p className="lp-index">§ 04 — Why upstream changed it</p>
          <h2 id="upstream-title">
            The reason, in the maintainers’ own words.
          </h2>
          <p className="lp-lede">
            A break is easier to fix when you know what the maintainers wanted
            instead. CodeIntent finds the upstream pull request behind each API
            change and quotes it. Each quote is compared word for word with the
            text on GitHub before it is shown, so nothing is paraphrased or
            invented.
          </p>
          <p className="lp-stat-line">
            <b>19 of 19</b> real API changes traced to the right upstream pull
            request.
          </p>
        </div>
        <ol
          className="lp-trail"
          data-reveal
          aria-label="How proxies= was removed from httpx"
        >
          {TRAIL.map((item) => (
            <li key={item.when}>
              <span className="lp-trail-node" aria-hidden="true" />
              <p className="lp-trail-when">
                {item.href ? <a href={item.href}>{item.when}</a> : item.when}
              </p>
              <p className="lp-trail-what">{item.what}</p>
              {item.quote ? (
                <blockquote className="lp-quote">
                  <p>“{item.quote}”</p>
                  {item.source ? (
                    <a href={item.source}>
                      Checked against the commit on GitHub
                    </a>
                  ) : null}
                </blockquote>
              ) : null}
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
