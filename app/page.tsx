import type { Metadata, Viewport } from "next";
import LandingPage from "@/components/landing/landing-page";

const title = "CodeIntent Dependency Check: know what an upgrade breaks";
const description =
  "A GitHub App for Python dependency pull requests. It compares both released versions against your code and posts one check and one comment: the exact file and line that breaks, what to use instead, and why upstream changed it.";

export const metadata: Metadata = {
  title,
  description,
  openGraph: {
    title,
    description,
    siteName: "CodeIntent",
    type: "website",
  },
  twitter: { card: "summary", title, description },
};

export const viewport: Viewport = { themeColor: "#0a0d11" };

export default function Home() {
  return <LandingPage />;
}
