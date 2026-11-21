<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

## Project notes

- Checks: `npm run check` (typecheck + prettier) and `npm run build`. Only one `next dev` may run per checkout; reuse the one on port 3210.
- Dashboard sections live under `app/dashboard/*` and share `app/dashboard/layout.tsx` (section menu). Data comes from the request-cached loaders in `lib/workspaces.ts`; tiles are in `components/dashboard/tiles.tsx`.
- Docs are MDX pages in `app/docs/**/page.mdx`; the sidebar order is `lib/docs.ts`. Plans and placeholder prices for `/pricing` and Billing are in `lib/plans.ts` (`BILLING_LIVE = false`).
