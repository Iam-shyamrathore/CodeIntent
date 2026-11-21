/** Shown at once while a dashboard section loads; reused from the client cache when moving between them. */
export default function Loading() {
  return (
    <div className="ci-loading" role="status" aria-live="polite">
      <span className="sr-only">Loading</span>
      <div className="ci-skel ci-skel-title" />
      <div className="ci-bento">
        <div className="ci-tile ci-skel-tile" />
        <div className="ci-tile ci-skel-tile ci-skel-wide" />
        <div className="ci-tile ci-skel-tile ci-skel-wide" />
      </div>
    </div>
  );
}
