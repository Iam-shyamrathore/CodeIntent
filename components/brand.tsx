import Link from "next/link";
export function Brand({ small = false }: { small?: boolean }) {
  return (
    <Link
      className={`brand ${small ? "brand-small" : ""}`}
      href="/"
      aria-label="Code Intent home"
    >
      <span className="brand-mark" aria-hidden="true">
        [<span>·</span>]
      </span>
      code intent<span className="brand-period">.</span>
    </Link>
  );
}
