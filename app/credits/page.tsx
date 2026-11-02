import Link from "next/link";
import { Brand } from "@/components/brand";
export default function Credits() {
  return (
    <main className="credits-page">
      <Brand />
      <h1>Sources & credits</h1>
      <p>
        The example uses a bounded collection of public HTTPX history.
        Repository imports capture public sources with explicit coverage limits.
      </p>
      <ul>
        <li>
          <a href="https://github.com/encode/httpx">
            HTTPX source and public discussions
          </a>
        </li>
        <li>
          <a href="https://github.com/CodeGraphContext/CodeGraphContext">
            CodeGraphContext · MIT · initial parser feasibility study
          </a>
        </li>
        <li>
          <a href="https://github.com/ishepard/pydriller">
            PyDriller · Apache-2.0 · historical demo collection
          </a>
        </li>
        <li>
          <a href="https://github.com/neo4j/neo4j-graphrag-python">
            Neo4j GraphRAG Python · Apache-2.0 / marked PSF portions
          </a>
        </li>
        <li>
          <a href="https://github.com/googleapis/python-genai">
            Google Gen AI SDK · Apache-2.0
          </a>
        </li>
        <li>
          <a href="https://github.com/radix-ui/primitives">Radix UI · MIT</a>
        </li>
        <li>
          <a href="https://github.com/IBM/plex">
            IBM Plex · SIL Open Font License
          </a>
        </li>
        <li>
          <a href="https://github.com/lucide-icons/lucide">Lucide · ISC</a>
        </li>
        <li>
          Design process informed by{" "}
          <a href="https://github.com/heydamir/unslop">
            Unslop by Damir Sokolovsky · CC BY 4.0
          </a>
        </li>
        <li>
          <a href="https://github.com/procrastinate-org/procrastinate">
            Procrastinate · MIT · durable PostgreSQL jobs
          </a>
        </li>
        <li>
          <a href="https://github.com/psycopg/psycopg">
            Psycopg · LGPL-3.0 · PostgreSQL adapter
          </a>
        </li>
        <li>
          <a href="https://github.com/Goldziher/tree-sitter-language-pack">
            Tree-sitter language pack · MIT / Apache-2.0 · individual grammar
            notices
          </a>
        </li>
        <li>
          <a href="https://github.com/xyflow/xyflow">
            React Flow · MIT · evidence graph
          </a>
        </li>
      </ul>
      <p>
        The product layout and evidence interactions are original to this
        project. Third-party package notices remain with their distributions.
      </p>
      <Link className="text-link" href="/investigate">
        Return to the investigation →
      </Link>
    </main>
  );
}
