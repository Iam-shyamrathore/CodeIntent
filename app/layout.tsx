import type { Metadata } from "next";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "./styles.css";

export const metadata: Metadata = {
  metadataBase: new URL(
    process.env.CODEINTENT_PUBLIC_URL || "http://localhost:3000",
  ),
  title: "CodeIntent Dependency Check",
  description:
    "A GitHub App that tells you whether a Python dependency upgrade breaks the code your repository actually has, at the exact file and line.",
  openGraph: {
    title: "CodeIntent Dependency Check",
    description:
      "One check and one comment on every dependency pull request: what breaks, what to use instead, and why upstream changed it.",
    siteName: "CodeIntent",
    type: "website",
  },
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" data-scroll-behavior="smooth">
      <body>{children}</body>
    </html>
  );
}
