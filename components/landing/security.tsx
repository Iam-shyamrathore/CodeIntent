const POINTS = [
  {
    title: "It never runs your code or the library",
    body: "Your repository and both releases are read as text. Nothing is built, installed, imported or executed, so a malicious release has nothing to run in.",
    glyph:
      "M2.5 12s3.5-6.5 9.5-6.5 9.5 6.5 9.5 6.5-3.5 6.5-9.5 6.5S2.5 12 2.5 12zM12 9.2a2.8 2.8 0 100 5.6 2.8 2.8 0 000-5.6z",
  },
  {
    title: "Least-privilege permissions",
    body: "Metadata and Contents are read-only. Pull requests and Checks are write, so the App can post its one comment and one check. Nothing else.",
    glyph: "M7 11V8a5 5 0 0110 0v3M5 11h14v9H5z",
  },
  {
    title: "Release files are verified",
    body: "Each release is downloaded from PyPI and its SHA-256 is checked against the published digest before it is unpacked, with limits on size and on paths inside the archive.",
    glyph: "M7 3.5h7l4 4v13H7zM14 3.5v4h4M9.5 12h6M9.5 15h6M9.5 18h3.5",
  },
  {
    title: "No model decides the verdict",
    body: "The verdict comes from fixed rules over the comparison. The same pull request gets the same verdict every time, and each finding cites the line in your code, the release and the upstream pull request behind it.",
    glyph: "M4 7h16M4 12h16M4 17h10",
  },
];

export function Security() {
  return (
    <section
      className="lp-section lp-security"
      id="security"
      aria-labelledby="security-title"
    >
      <div className="lp-wrap">
        <div className="lp-section-head" data-reveal>
          <p className="lp-index">§ 09 — Security and honesty</p>
          <h2 id="security-title">It reads. It never runs.</h2>
        </div>
        <ul className="lp-security-grid" data-reveal>
          {POINTS.map((point, index) => (
            <li key={point.title}>
              <span className="lp-security-no">
                {String(index + 1).padStart(2, "0")}
              </span>
              <svg
                className="lp-security-glyph"
                viewBox="0 0 24 24"
                aria-hidden="true"
                focusable="false"
              >
                <path d={point.glyph} />
              </svg>
              <h3>{point.title}</h3>
              <p>{point.body}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
