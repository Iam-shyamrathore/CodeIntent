import Link from "next/link";
import { Brand } from "@/components/brand";
export default function NotFound() {
  return (
    <main className="credits-page">
      <Brand />
      <h1>Nothing at this address.</h1>
      <p>
        This page or investigation could not be found. Your repositories and
        saved evidence are a good place to start.
      </p>
      <Link className="text-link" href="/repositories">
        Open repositories →
      </Link>
    </main>
  );
}
