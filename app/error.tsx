"use client";
import Link from "next/link";
import { Brand } from "@/components/brand";
export default function ErrorPage({
  retry,
}: {
  error: unknown;
  retry: () => void;
}) {
  return (
    <main className="credits-page">
      <Brand />
      <h1>This view could not be loaded.</h1>
      <p>
        Your saved evidence is still stored. Try loading this view again, or
        return to your repositories.
      </p>
      <div className="error-actions">
        <button className="primary-button" onClick={retry}>
          Try again
        </button>
        <Link href="/repositories">Open repositories →</Link>
      </div>
    </main>
  );
}
