import Link from "next/link";

export type FilterOption = { value: string; label: string; count: number };

/** One row of filter chips that are plain links, so every filtered view has its own URL. */
export function Filters({
  label,
  options,
  current,
  href,
}: {
  label: string;
  options: FilterOption[];
  current: string;
  href: (value: string) => string;
}) {
  return (
    <nav className="ci-filters" aria-label={label}>
      {options.map((o) => (
        <Link
          key={o.value}
          href={href(o.value)}
          scroll={false}
          aria-current={o.value === current ? "true" : undefined}
          data-empty={o.count === 0 ? "" : undefined}
        >
          {o.label}
          <span>{o.count}</span>
        </Link>
      ))}
    </nav>
  );
}

export function pick<T extends string>(
  value: string | string[] | undefined,
  allowed: readonly T[],
  fallback: T,
): T {
  const v = Array.isArray(value) ? value[0] : value;
  return (allowed as readonly string[]).includes(v || "") ? (v as T) : fallback;
}
