import Landing from "@/components/landing";
import { readStudy } from "@/lib/study";
export const dynamic = "force-dynamic";
export default function Home() {
  return <Landing study={readStudy()} />;
}
