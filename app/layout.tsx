import type { Metadata, Viewport } from "next";
import { Doto, Martian_Mono, Mona_Sans } from "next/font/google";
import "./styles.css";

/** Mona Sans carries the voice; its width axis gives the display cut. */
const sans = Mona_Sans({
  subsets: ["latin"],
  axes: ["wdth"],
  variable: "--font-body",
  display: "swap",
});
/** Martian Mono only for real code: file paths, symbols, versions. */
const code = Martian_Mono({
  subsets: ["latin"],
  axes: ["wdth"],
  variable: "--font-code",
  display: "swap",
});
/** Doto, a dot-matrix face, only for step numerals and counts. */
const dots = Doto({
  subsets: ["latin"],
  axes: ["ROND"],
  variable: "--font-dots",
  display: "swap",
  preload: false,
});

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

export const viewport: Viewport = {
  themeColor: "#0b0b0a",
  colorScheme: "dark",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      data-scroll-behavior="smooth"
      className={`${sans.variable} ${code.variable} ${dots.variable}`}
    >
      <body>{children}</body>
    </html>
  );
}
