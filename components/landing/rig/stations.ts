/** The five stations of the inspection bench, with the real openai-python / httpx case. */
export interface Station {
  step: string;
  name: string;
  title: string;
  body: string;
  readout: string;
}

export const STATIONS: Station[] = [
  {
    step: "01",
    name: "Manifest",
    title: "Reads what the pull request changes",
    body: "httpx moves from 0.27.2 to 0.28.0. It makes no difference whether Dependabot, Renovate or a developer opened the pull request.",
    readout: "httpx 0.27.2 → 0.28.0",
  },
  {
    step: "02",
    name: "Your code",
    title: "Finds every place your code uses it",
    body: "Each import of httpx and each call into it, with the arguments passed. Three calls pass proxies=.",
    readout: "3 calls pass proxies=",
  },
  {
    step: "03",
    name: "Both releases",
    title: "Compares the two released versions",
    body: "Both releases come from PyPI and are checked against their SHA-256 before they are read. Nothing is installed or run. In 0.28.0, Client and AsyncClient no longer accept proxies=.",
    readout: "Client(proxies=) removed",
  },
  {
    step: "04",
    name: "Upstream",
    title: "Finds why upstream changed it",
    body: "The upstream pull request that removed it, encode/httpx#3319. Every quote is checked word for word against GitHub.",
    readout: "encode/httpx#3319",
  },
  {
    step: "05",
    name: "Verdict",
    title: "Gives one verdict from fixed rules",
    body: "Your code passes an argument that was removed, and nothing guards the call. The verdict is Breaks you, at src/openai/_base_client.py:857 and two other places.",
    readout: "Breaks you · 3 places",
  },
];
