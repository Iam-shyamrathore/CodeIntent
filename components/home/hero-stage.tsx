"use client";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useState } from "react";
import { Mark } from "@/components/brand";

const HeroScene = dynamic(() => import("./hero-scene"), { ssr: false });

type Mode = "poster" | "live" | "still";

function webgl2() {
  try {
    const gl = document.createElement("canvas").getContext("webgl2");
    gl?.getExtension("WEBGL_lose_context")?.loseContext();
    return Boolean(gl);
  } catch {
    return false;
  }
}

/**
 * The hero stage. The halftone mark is the poster: it is what shows without WebGL, before
 * three.js has loaded, and if the context is lost. The live scene fades in over it.
 */
export function HeroStage({ children }: { children: React.ReactNode }) {
  const [stage, setStage] = useState<HTMLDivElement | null>(null);
  const [mode, setMode] = useState<Mode>("poster");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!webgl2()) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const start = () => setMode(still ? "still" : "live");
    if ("requestIdleCallback" in window) {
      const id = window.requestIdleCallback(start, { timeout: 1200 });
      return () => window.cancelIdleCallback(id);
    }
    const id = setTimeout(start, 200);
    return () => clearTimeout(id);
  }, []);

  const onReady = useCallback(() => setReady(true), []);
  const onFail = useCallback(() => {
    setReady(false);
    setMode("poster");
  }, []);

  return (
    <div
      className="ci-stage"
      ref={setStage}
      data-ready={ready ? "" : undefined}
    >
      <div
        className="ci-stage-art"
        role="img"
        aria-label="A dependency package being scanned. One spot on it turns red: the line in your code that the upgrade breaks."
      >
        <div className="ci-stage-poster">
          <Mark className="ci-stage-mark" />
        </div>
        {mode !== "poster" && stage && (
          <HeroScene
            still={mode === "still"}
            stage={stage}
            onReady={onReady}
            onFail={onFail}
          />
        )}
      </div>
      <span className="ci-leader" aria-hidden="true" />
      {children}
    </div>
  );
}
