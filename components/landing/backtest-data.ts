import "server-only";
import { readFile } from "node:fs/promises";
import path from "node:path";

export interface Backtest {
  breaks: { caught: number; total: number } | null;
  harmless: {
    false_breaks: number;
    total: number;
    wilson_upper: number | null;
  } | null;
  updated: string | null;
}

const count = (value: unknown) =>
  typeof value === "number" && Number.isInteger(value) && value >= 0;

/** Reads public/backtest.json when it exists; any missing or malformed part becomes null. */
export async function readBacktest(): Promise<Backtest> {
  let raw: unknown;
  try {
    raw = JSON.parse(
      await readFile(
        path.join(process.cwd(), "public", "backtest.json"),
        "utf8",
      ),
    );
  } catch {
    return { breaks: null, harmless: null, updated: null };
  }
  const data = (raw ?? {}) as Record<string, Record<string, unknown> | null>;
  const breaks = data.breaks;
  const harmless = data.harmless;
  const updated = (raw as { updated?: unknown })?.updated;
  return {
    breaks:
      breaks &&
      count(breaks.caught) &&
      count(breaks.total) &&
      Number(breaks.total) > 0
        ? { caught: Number(breaks.caught), total: Number(breaks.total) }
        : null,
    harmless:
      harmless &&
      count(harmless.false_breaks) &&
      count(harmless.total) &&
      Number(harmless.total) > 0
        ? {
            false_breaks: Number(harmless.false_breaks),
            total: Number(harmless.total),
            wilson_upper:
              typeof harmless.wilson_upper === "number" &&
              harmless.wilson_upper >= 0 &&
              harmless.wilson_upper <= 1
                ? harmless.wilson_upper
                : null,
          }
        : null,
    updated:
      typeof updated === "string" && !Number.isNaN(Date.parse(updated))
        ? updated
        : null,
  };
}
