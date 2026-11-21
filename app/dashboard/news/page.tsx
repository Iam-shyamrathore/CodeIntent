import { DashboardGate, PageHead } from "@/components/dashboard/tiles";
import { ArrowOut } from "@/components/site/icons";
import { formatDate } from "@/lib/dashboard";
import { loadContext, loadNews } from "@/lib/workspaces";

export const metadata = { title: "Security news · CodeIntent" };

const AFFECTS = {
  yes: "Your locked version is in the reported range",
  maybe: "No affected range given: check your version",
  no: "Your locked version is outside the reported range",
} as const;

/** Security reports CodeIntent's agent found on the web for the packages the workspace locks. */
export default async function News() {
  const context = await loadContext();
  if (context.state !== "ok")
    return <DashboardGate gate={context} next="/dashboard/news" />;
  const items = await loadNews();
  const list = items || [];
  const relevant = list.filter((n) => n.affects !== "no" && !n.in_osv).length;
  return (
    <>
      <PageHead
        title={
          list.length === 0
            ? "No security news for your packages"
            : `${relevant} report${relevant === 1 ? "" : "s"} not yet in OSV.dev`
        }
        intro="Every day CodeIntent's agent searches the web for security reports about the packages your repositories lock, often before advisory databases list them. It only reports pages it read, with their link; CodeIntent decides whether your version is affected. Agent findings: check the source."
      />
      {items === null ? (
        <p className="ci-alert" role="alert">
          Security news could not be loaded.
        </p>
      ) : list.length === 0 ? (
        <p className="ci-note">
          Nothing found yet. The search runs daily once your repositories have
          been scanned.
        </p>
      ) : (
        <div className="ci-news">
          {list.map((n) => (
            <article
              key={`${n.installation_id}-${n.package}-${n.key}`}
              className="ci-tile ci-trace"
              data-affects={n.affects}
            >
              <header className="ci-tile-head">
                <h3>
                  <code translate="no">{n.package}</code> {n.item.title}
                </h3>
                <span className="ci-row-meta">
                  {n.item.severity} · first seen {formatDate(n.first_seen)}
                </span>
              </header>
              <p>{n.item.summary}</p>
              <p className="ci-note">
                {AFFECTS[n.affects]}
                {n.item.affected && (
                  <>
                    {" "}
                    (<code translate="no">{n.item.affected}</code>)
                  </>
                )}
                {n.item.fixed_in && `, fixed in ${n.item.fixed_in}`}.{" "}
                {n.in_osv ? "OSV.dev lists it too." : "Not in OSV.dev yet."}
              </p>
              <p className="ci-note">
                {n.item.ids.length > 0 && (
                  <>
                    {n.item.ids.join(", ")}
                    {" · "}
                  </>
                )}
                Used by {n.repositories.join(", ")}
                {" · "}
                <a href={n.item.url} rel="noopener noreferrer nofollow">
                  Source <ArrowOut size={12} />
                </a>
              </p>
            </article>
          ))}
        </div>
      )}
    </>
  );
}
