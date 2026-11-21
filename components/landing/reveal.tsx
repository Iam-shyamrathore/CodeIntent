"use client";

import { useEffect } from "react";

/**
 * Fades sections up as they enter the viewport. Content is visible without JavaScript; only
 * elements still below the fold when this runs are hidden, so nothing on screen ever blinks.
 */
export function Reveal() {
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const nodes = Array.from(
      document.querySelectorAll<HTMLElement>(".lp [data-reveal]"),
    );
    const fold = window.innerHeight;
    const pending = nodes.filter(
      (node) => node.getBoundingClientRect().top > fold * 0.92,
    );
    pending.forEach((node) => node.setAttribute("data-reveal", "waiting"));
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          entry.target.setAttribute("data-reveal", "shown");
          observer.unobserve(entry.target);
        }
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.08 },
    );
    pending.forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, []);
  return null;
}
