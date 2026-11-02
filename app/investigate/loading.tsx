import { Brand } from "@/components/brand";
export default function Loading() {
  return (
    <main className="credits-page">
      <Brand />
      <p role="status" style={{ marginTop: 64 }}>
        Opening the evidence workspace…
      </p>
    </main>
  );
}
