# The graph in Neo4j

Two graphs share one database:

- **The public ecosystem graph:** every Python package that a watched repository or an indexed open-source
  project depends on, directly or transitively. It holds each package's releases, the resolved dependency
  tree between releases (from deps.dev), the GitHub repository behind each package (stars, licence, OpenSSF
  Scorecard), known advisories (OSV.dev), the API changes CodeIntent has found and the upstream PRs and
  library files behind them. These are shared `pub|` nodes with no `ws`.
- **Workspace graphs:** your repositories, the lines of code that use each library, runs, findings and pins.
  These carry `ws` (the installation id) and link into the public graph.

The 67 real open-source projects from the backtest set (openai-python, flask, celery, langchain, saleor, ...)
are seeded with `python -m scripts.seed_ecosystem`: only their manifest and lock files are read.

## The ecosystem graph

```
(:SourceRepo)-[:PUBLISHES]->(:Package)-[:HAS_RELEASE]->(:Release)-[:DEPENDS_ON {requirement}]->(:Release)
(:SourceRepo {seeded: true})-[:REQUIRES {specifier}]->(:Package)    (:SourceRepo)-[:LOCKS]->(:Release)
(:Repository)-[:LOCKS {direct}]->(:Release)     (:Advisory)-[:AFFECTS]->(:Release)
(:APIChange)-[:IN_RELEASE]->(:Release)          (:APIChange)-[:IN_FILE {line}]->(:Module)<-[:SHIPS]-(:Release)
(:APIChange)-[:CHANGED_IN]->(:UpstreamPR)-[:IN_REPO]->(:SourceRepo)
```

**The size of it:**

```cypher
MATCH (n) WHERE n.uid STARTS WITH 'pub|'
RETURN labels(n)[0] AS kind, count(*) AS nodes ORDER BY nodes DESC
```

**One package's neighbourhood: who publishes it, what it needs, what needs it.**

```cypher
MATCH (p:Package {name: 'httpcore'})
OPTIONAL MATCH pub = (:SourceRepo)-[:PUBLISHES]->(p)
OPTIONAL MATCH needs = (p)-[:HAS_RELEASE]->(:Release)-[:DEPENDS_ON]->(:Release)
OPTIONAL MATCH needed = (:Release)-[:DEPENDS_ON]->(:Release {package: 'httpcore'})
RETURN pub, needs, needed
```

**Blast radius across open source: every indexed project that depends on urllib3, at any depth.**

```cypher
MATCH (t:Release {package: 'urllib3'})
MATCH p = (proj:SourceRepo {seeded: true})-[:LOCKS]->(:Release)-[:DEPENDS_ON*0..5]->(t)
RETURN p LIMIT 150
```

**Why is a package installed?** The shortest chain from what a repository declares:

```cypher
MATCH (r:SourceRepo {name: 'openai/openai-python'})-[:LOCKS {direct: true}]->(d:Release)
MATCH (t:Release {package: 'h11'})
MATCH p = shortestPath((d)-[:DEPENDS_ON*0..8]->(t))
RETURN p ORDER BY length(p) LIMIT 3
```

**Advisories that arrive through other packages**, in your repositories:

```cypher
MATCH (r:Repository {ws: $ws})-[l:LOCKS]->(v:Release)<-[:AFFECTS]-(a:Advisory)
WHERE NOT coalesce(l.direct, true)
MATCH (r)-[:LOCKS {direct: true}]->(d:Release)
MATCH p = (d)-[:DEPENDS_ON*1..6]->(:Release {package: v.package})
RETURN r, p, a LIMIT 50
```

**Risky foundations: packages many projects rely on whose repository is not actively maintained.**

```cypher
MATCH (s:SourceRepo)-[:PUBLISHES]->(p:Package)-[:HAS_RELEASE]->(rel:Release)<-[:LOCKS]-(x)
WHERE s.maintained = 0
RETURN p.name AS package, s.name AS repository, s.scorecard AS scorecard,
       count(DISTINCT x) AS projects ORDER BY projects DESC LIMIT 20
```

**From a line of your code to the file in the library that changed, and the PR that changed it:**

```cypher
MATCH p = (l:CodeLine {ws: $ws})<-[:AT]-(:Finding)-[:CAUSED_BY]->(c:APIChange)-[:IN_FILE]->(:Module)
OPTIONAL MATCH q = (c)-[:CHANGED_IN]->(:UpstreamPR)-[:IN_REPO]->(:SourceRepo)
RETURN p, q
```

# The workspace graph in Neo4j

Every pull request check, repository scan and agent call is recorded in PostgreSQL as a run, then copied into
Neo4j as part of its workspace's graph (one GitHub App installation = one workspace). The graph is what answers
the questions that cross repositories: **what does this library change touch, everywhere?**

- **Where it is used in the product:** the dashboard's **Impact** page, the graph on each run report
  (`/runs/{id}`), the MCP tools `impact` and `who_uses`, and Telegram's `/impact`.
- **What writes it:** `codeintent/workspace_graph.py`, run by the durable job `project_run` a few seconds after
  each run finishes, plus a catch-up every five minutes. PostgreSQL stays the source of truth; a workspace's
  graph can be rebuilt from it at any time (`workspace_graph.rebuild(installation_id)`).
- **Isolation:** every node has `ws` (the installation id) and a `uid` starting with it. No node is shared
  between workspaces; every query below filters on `ws`.

## Model

```
(:Workspace)-[:WATCHES]->(:Repository)-[:CONTAINS]->(:File)-[:HAS_LINE]->(:CodeLine)-[:USES]->(:Symbol)
(:Repository)-[:DEPENDS_ON]->(:Package)-[:HAS_RELEASE]->(:Release)<-[:LOCKS]-(:Repository)
(:Workspace)-[:RAN]->(:Run)-[:ANALYSED]->(:Repository)        (:Run)-[:HAD_STEP]->(:Step)
(:Run)-[:CHECKED]->(:Upgrade)-[:FROM|TO]->(:Release)          (:Upgrade)-[:FOUND]->(:Finding)-[:AT]->(:CodeLine)
(:Finding)-[:CAUSED_BY]->(:APIChange)-[:AFFECTS]->(:Symbol)   (:APIChange)-[:IN_RELEASE]->(:Release)
(:APIChange)-[:CHANGED_IN|DEPRECATED_IN]->(:UpstreamPR)       (:Advisory)-[:AFFECTS]->(:Release)
(:Repository)-[:DECLARES]->(:Pin)-[:RESTRICTS]->(:Package)    (:Pin)-[:HOLDS_BACK]->(:Release)
(:Pin)-[:ADDED_IN]->(:Commit)-[:MERGED_IN]->(:PullRequest)    (:AgentToken)-[:ASKED]->(:Run)
```

`USES` edges come from scans of each default branch only, carry the keyword arguments passed, and are removed
when a later scan no longer sees them, so they describe the code as it is now. Every label has a uniqueness
constraint on `uid` and an index on `ws`.

## Opening it in Neo4j Browser

1. Open the Aura console (console.neo4j.io), choose the instance, then **Query**. Sign in with the
   `NEO4J_USERNAME` / `NEO4J_PASSWORD` from Heroku config.
2. Load the style: drag `docs/neo4j/codeintent.grass` onto the Browser window, or run `:style` and paste it.
   Breaking findings and changes are red, upstream PRs green, your code white, library symbols blue.
3. Set the workspace once per session (the demo account's installation):

   ```
   :param ws => 184373976
   ```

## Queries for the demo

**A user's whole workspace: what it watches, what each scan found, and why.**

```cypher
MATCH p = (w:Workspace {ws: $ws})-[:WATCHES]->(r:Repository)<-[:ANALYSED]-(run:Run)
          -[:CHECKED]->(u:Upgrade)-[:FOUND]->(:Finding)-[:CAUSED_BY]->(c:APIChange)-[:CHANGED_IN]->(:UpstreamPR)
RETURN p
```

**One run**, the same chain the run report draws. Copy the run id from the dashboard's **Runs** page:

```cypher
:param run => '20343a52-eff6-4b9d-be96-19d360fbf7a1'
```

```cypher
MATCH (run:Run {ws: $ws, id: $run})
OPTIONAL MATCH steps = (run)-[:HAD_STEP]->(:Step)
OPTIONAL MATCH why = (run)-[:ANALYSED]->(:Repository)
OPTIONAL MATCH found = (run)-[:CHECKED]->(:Upgrade)-[:FOUND]->(:Finding)-[:AT]->(:CodeLine)
OPTIONAL MATCH cause = (run)-[:CHECKED]->(:Upgrade)-[:FOUND]->(:Finding)-[:CAUSED_BY]->(:APIChange)
                       -[:CHANGED_IN|DEPRECATED_IN]->(:UpstreamPR)
RETURN run, steps, why, found, cause
```

**Impact: every line a change touches, in every repository.** Lines with no `Finding` were found through
the graph alone: the same call with the same argument in a repository whose upgrade nobody compared yet.

```cypher
MATCH (c:APIChange {ws: $ws, package: 'httpx', version: '0.28.1'})-[:AFFECTS]->(s:Symbol)
      <-[u:USES]-(l:CodeLine)<-[:HAS_LINE]-(:File)<-[:CONTAINS]-(r:Repository)
WHERE c.parameter IS NULL OR c.parameter IN u.keywords
OPTIONAL MATCH (f:Finding)-[:AT]->(l) WHERE (f)-[:CAUSED_BY]->(c)
RETURN r.name AS repository, l.name AS line, l.code AS code, c.name AS change,
       c.replacement AS use_instead, f IS NOT NULL AS compared
ORDER BY repository, line
```

Draw it instead of tabling it:

```cypher
MATCH p = (c:APIChange {ws: $ws, package: 'httpx'})-[:AFFECTS]->(:Symbol)<-[:USES]-(:CodeLine)
          <-[:HAS_LINE]-(:File)<-[:CONTAINS]-(:Repository)
RETURN p
```

**Why upstream changed it**, from your line to the library's own PRs:

```cypher
MATCH p = (l:CodeLine {ws: $ws})<-[:AT]-(:Finding)-[:CAUSED_BY]->(:APIChange)-[:CHANGED_IN|DEPRECATED_IN]->(:UpstreamPR)
RETURN p
```

**Who uses a library**, from each default branch's latest scan:

```cypher
MATCH p = (:Repository {ws: $ws})-[:CONTAINS]->(:File)-[:HAS_LINE]->(:CodeLine)-[:USES]->(s:Symbol {package: 'httpx'})
RETURN p
```

**Pins holding back a release, and the commit that added each:**

```cypher
MATCH p = (:Repository {ws: $ws})-[:DECLARES]->(pin:Pin)-[:HOLDS_BACK]->(:Release)
OPTIONAL MATCH q = (pin)-[:ADDED_IN]->(:Commit)-[:MERGED_IN]->(:PullRequest)
RETURN p, q
```

**Failures: every run that stopped, and the step it stopped at:**

```cypher
MATCH p = (run:Run {ws: $ws, status: 'failed'})-[:HAD_STEP]->(s:Step {status: 'failed'})
RETURN p
```

**What agents asked:**

```cypher
MATCH p = (:AgentToken {ws: $ws})-[:ASKED]->(:Run)-[:CHECKED|ANALYSED]->()
RETURN p
```

**Advisories on what each repository runs now:**

```cypher
MATCH p = (:Repository {ws: $ws})-[:LOCKS]->(:Release)<-[:AFFECTS]-(:Advisory)
RETURN p
```
