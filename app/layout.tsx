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
  title: "Code Intent — Know why this code exists",
  description:
    "Investigate the decisions behind a codebase through its code, commits and discussions.",
  openGraph: {
    title: "Code Intent — Know why this code exists",
    description:
      "Follow the decisions, discussions and changes behind a real repository. Every claim cites its source.",
    siteName: "Code Intent",
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
