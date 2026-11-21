/**
 * Plans shown on /pricing and /dashboard/billing. Billing is not live: every plan is free during the beta,
 * and these prices are placeholders until a payment provider is connected.
 */
export type Plan = {
  id: "free" | "team" | "self-hosted";
  name: string;
  price: string;
  cadence: string;
  summary: string;
  features: string[];
  cta: { label: string; href: string };
  featured?: boolean;
};

export const BILLING_LIVE = false;

export const PLANS: Plan[] = [
  {
    id: "free",
    name: "Free",
    price: "$0",
    cadence: "forever",
    summary: "For open-source and personal repositories.",
    features: [
      "A check and a comment on every dependency pull request",
      "Before you upgrade, checked daily",
      "Telegram alerts",
      "Public repositories",
    ],
    cta: { label: "Install on GitHub", href: "/setup" },
  },
  {
    id: "team",
    name: "Team",
    price: "$29",
    cadence: "per month, per GitHub account",
    summary: "For teams shipping private Python services.",
    features: [
      "Everything in Free",
      "Private repositories",
      "AI agent tokens over MCP",
      "Pin origins: the commit and PR behind every pin",
    ],
    cta: { label: "Start with the beta", href: "/setup" },
    featured: true,
  },
  {
    id: "self-hosted",
    name: "Self-hosted",
    price: "Custom",
    cadence: "annual",
    summary: "Run CodeIntent on your own infrastructure.",
    features: [
      "Your own GitHub App and keys",
      "Docker Compose deployment",
      "Operator view and failure alerts",
      "Code never leaves your network",
    ],
    cta: {
      label: "Read the deployment guide",
      href: "https://github.com/Iam-shyamrathore/CodeIntent/blob/main/docs/deployment.md",
    },
  },
];
