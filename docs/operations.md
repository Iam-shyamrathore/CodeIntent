# Operations and recovery

## Normal operation

Only the web service receives public traffic. API startup runs numbered PostgreSQL migrations; its service key is supplied by the web server. The worker processes one import at a time and Procrastinate maintains worker heartbeats independently of synchronous import work.

Imports move through collection, parsing, decision extraction, projection, embeddings and validation. The immutable source capture and extracted decisions are checkpoints in PostgreSQL. Graph writes use scoped MERGE keys and embedding batches skip already written vectors. Automatic retries are bounded; a failed job can also be retried from Repositories. Cancellation is checked between stages, before publish, and while collection reports progress. It does not interrupt an already in-flight provider request.

An index is published only after all source nodes and embeddings are present. The old ready index remains selected until that transaction commits. Captured sources and pending index records are retained after failure so the operation is diagnosable and resumable. Repeated submissions while the same repository has an active import return that job instead of duplicating it.

Worker-loss recovery uses the queue's worker heartbeat records. The maintenance task requeues imports assigned to workers whose heartbeat is over three minutes old, and orphaned imports whose worker record has already been pruned by the queue. The normal repository lock still applies. A browser disconnect does not cancel an import.

## Back up

PostgreSQL is authoritative. Keep the backup outside the container volume and restrict its access.

```sh
docker compose exec -T postgres pg_dump -U codeintent -d codeintent -Fc > codeintent-ledger.dump
```

Back up Neo4j's volume consistently using the image/provider's supported backup process, or rebuild its projection from the ledger. Do not copy a live database volume into a second running database process. Do not use `docker compose down -v` for routine shutdown or upgrades.

For an empty replacement PostgreSQL database, stop the API and worker before restoration:

```sh
docker compose stop api worker
cat codeintent-ledger.dump | docker compose exec -T postgres pg_restore -U codeintent -d codeintent --no-owner --exit-on-error
docker compose up -d api worker
```

Restore into an empty compatible database; this command intentionally omits destructive `--clean`. Keep the pre-upgrade backup until smoke tests succeed.

## Rebuild the graph

Use the same model configuration that created the indexes. The helper preserves stored index identities and rebuilds published snapshots from PostgreSQL. It uses fresh embeddings and therefore requires Vertex.

```sh
docker compose exec api python -m scripts.rebuild_graph
```

The existing projection is updated idempotently; the helper does not delete unrelated graph data. For a replacement empty graph service, configure its URI/password first. Then verify `/api/service/ready` and a new investigation.

## Upgrade and rollback

Record the source commit and image digests, take a PostgreSQL backup, build the intended images, then use `docker compose up -d --build`. Numbered migrations are forward-only and guarded by an advisory lock. The shipped migrations add tables/columns and do not drop source or report data.

For application rollback, redeploy the previous image tags against a compatible schema. If a future migration changes schema incompatibly, restore the pre-upgrade backup into a separate database and point the previous application there. Do not run two database containers against one volume.

## Investigations and cost controls

Two uncached investigations can execute concurrently per API process. PostgreSQL enforces client/global daily question quotas and the import quota. Cache identity includes exact question, immutable index, model and evidence policy. Identical saved answers do not consume model quota. A cache hit remains visibly saved and retains its original generation time.

A transient Vertex error returns a recoverable error without displaying an unverified answer. Invalid passage references receive one generation repair; both attempts are validated before release. The independent model support review can remove claims; its own provider failure withholds the result. Existing public report links continue to read their stored result.

Logs record operation IDs and exception categories, not raw provider exceptions or secrets. Avoid enabling SDK HTTP debug logs on a deployment containing credentials. PostgreSQL stores public source bodies and model output; backups should still be restricted.

## Scope and capacity

This is a bounded public-repository workspace, not a full-history code host, private-repository product or tenant-isolated SaaS. Source limits are shown in the UI and README. The supplied local container test used the declared images; it does not establish an arbitrary managed Neo4j tier's compatibility or production throughput.

Allocate memory to Neo4j and the worker based on observed source size. The Compose graph uses a 512 MB maximum heap and 256 MB page cache; allow additional memory for the other services and image builds. Before increasing import limits or adding API replicas, measure queue duration, provider usage, database/graph load and investigation latency under that load.
