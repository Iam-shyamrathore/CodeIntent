import {
  DashboardGate,
  InstallTile,
  PageHead,
  RepoGrid,
  UnavailableNotice,
} from "@/components/dashboard/tiles";
import { byActivity, loadContext, pageNumber } from "@/lib/workspaces";

export const metadata = { title: "Repositories · CodeIntent" };

const PER_PAGE = 12;

export default async function Repositories({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const [context, query] = await Promise.all([loadContext(), searchParams]);
  if (context.state !== "ok")
    return <DashboardGate gate={context} next="/dashboard/repositories" />;
  const q = (typeof query.q === "string" ? query.q : "").trim().slice(0, 100);
  const matching = context.repos
    .filter((r) => !q || r.full_name.toLowerCase().includes(q.toLowerCase()))
    .sort(byActivity);
  const pages = Math.max(1, Math.ceil(matching.length / PER_PAGE));
  const page = pageNumber(query.page, pages);
  const href = (p: number) => {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (p > 1) params.set("page", String(p));
    const s = params.toString();
    return `/dashboard/repositories${s ? `?${s}` : ""}`;
  };
  return (
    <>
      <PageHead
        title="Repositories"
        intro="Every repository the App can read, most recently active first. Open one for its pull requests, pins and upcoming breakage."
      />
      <UnavailableNotice
        repos={context.workspaces.some((w) => w.repos.state === "unavailable")}
      />
      <div className="ci-bento">
        <RepoGrid
          repos={matching.slice((page - 1) * PER_PAGE, page * PER_PAGE)}
          total={context.repos.length}
          page={page}
          pages={pages}
          pageHref={href}
          query={q}
        />
        <InstallTile />
      </div>
    </>
  );
}
