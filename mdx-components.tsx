import type { MDXComponents } from "mdx/types";
import Link from "next/link";

/** Docs markdown: internal links stay client-side, wide tables scroll inside their own box. */
const components: MDXComponents = {
  a: ({ href = "", children, ...rest }) =>
    href.startsWith("/") || href.startsWith("#") ? (
      <Link href={href} {...rest}>
        {children}
      </Link>
    ) : (
      <a href={href} rel="noreferrer" {...rest}>
        {children}
      </a>
    ),
  table: (props) => (
    <div className="ci-prose-table">
      <table {...props} />
    </div>
  ),
};

export function useMDXComponents(): MDXComponents {
  return components;
}
