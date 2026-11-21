"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from "react";
import { translateAlong, type Flat } from "../iso/iso-kit";
import { SCAN_SPAN, drawerMarkup, needle, scanLine } from "./frame";
import type { Station } from "./stations";
import {
  DRAWER_OUT,
  DRAWER_Z,
  HEIGHT,
  P,
  PRESS_Y,
  STAMP_TRAVEL,
  STATION_X,
  WIDTH,
  at,
} from "./view";

type Layers = Record<
  | "base"
  | "rackBack"
  | "rackCard"
  | "rackFront"
  | "scanBack"
  | "scanTop"
  | "compare"
  | "cabinet"
  | "pressBack"
  | "pressRod"
  | "pressTop"
  | "rails"
  | "carriage"
  | "mark",
  ReactNode
>;

const DWELL = [2.8, 3.2, 3.4, 3.4, 4.6];
const HANDS_OFF = 14;
const STIFF = 16;
const DRAG = 7.4;
const RISE = 7;
const NEEDLE = 1.15;

const follow = (now: number, target: number, dt: number, seconds: number) => {
  const next = now + (target - now) * (1 - Math.exp(-dt / seconds));
  return Math.abs(target - next) < 1e-3 ? target : next;
};
const smooth = (t: number) => {
  const u = Math.min(1, Math.max(0, t));
  return u * u * (3 - 2 * u);
};
/** The stamp's travel over time: falls in 0.32 s, dwells, lifts by 1.1 s. */
const pressAt = (t: number) => {
  if (t < 0) return 0;
  if (t < 0.32) return (t / 0.32) ** 2;
  if (t < 0.62) return 1;
  return 1 - smooth((t - 0.62) / 0.5);
};

export function RigLive({
  stations,
  layers,
  restNeedle,
  restDrawer,
  hub,
}: {
  stations: Station[];
  layers: Layers;
  restNeedle: string;
  restDrawer: string;
  hub: Flat;
}) {
  const [active, setActive] = useState(0);
  const [inView, setInView] = useState(false);
  const [still, setStill] = useState(false);
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(false);
  pausedRef.current = paused;
  const root = useRef<HTMLDivElement>(null);
  const pan = useRef<HTMLDivElement>(null);
  const carriage = useRef<SVGGElement>(null);
  const rackCard = useRef<SVGGElement>(null);
  const scan = useRef<SVGPathElement>(null);
  const needlePath = useRef<SVGPathElement>(null);
  const drawer = useRef<SVGGElement>(null);
  const rod = useRef<SVGGElement>(null);
  const mark = useRef<SVGGElement>(null);
  const touched = useRef(-Infinity);
  const activeRef = useRef(0);
  activeRef.current = active;
  const state = useRef({
    x: STATION_X[0] as number,
    v: 0,
    acts: [0, 0, 0, 0, 0],
    scanT: 0,
    pressT: -1,
    stamped: 0,
    dwell: 0,
    clock: 0,
    drawn: {
      x: NaN,
      rise: NaN,
      scan: NaN,
      needle: NaN,
      drawer: NaN,
      press: NaN,
      mark: NaN,
    },
  });

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setStill(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    const node = root.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => setInView(Boolean(entries.at(-1)?.isIntersecting)),
      { rootMargin: "80px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const draw = useCallback(() => {
    const s = state.current;
    const d = s.drawn;
    const fix = (v: number) => Math.round(v * 100) / 100;
    if (fix(s.x) !== d.x && carriage.current) {
      d.x = fix(s.x);
      carriage.current.setAttribute(
        "transform",
        translateAlong(P, [s.x, 0, 0]),
      );
    }
    const rise = fix(RISE * smooth(s.acts[0]!));
    if (rise !== d.rise && rackCard.current) {
      d.rise = rise;
      rackCard.current.setAttribute(
        "transform",
        translateAlong(P, [0, 0, rise]),
      );
    }
    const scanOn = s.acts[1]!;
    const scanY =
      SCAN_SPAN.from +
      (SCAN_SPAN.to - SCAN_SPAN.from) * (0.5 - 0.5 * Math.cos(s.scanT * 2.6));
    const scanKey = fix(scanOn) * 1000 + fix(scanY);
    if (scanKey !== d.scan && scan.current) {
      d.scan = scanKey;
      scan.current.setAttribute("d", scanLine(scanY));
      scan.current.style.opacity = String(fix(scanOn));
    }
    const angle = fix(NEEDLE * smooth(s.acts[2]!));
    if (angle !== d.needle && needlePath.current) {
      d.needle = angle;
      needlePath.current.setAttribute("d", needle(angle));
    }
    const out = Math.round(DRAWER_OUT * smooth(s.acts[3]!) * 10) / 10;
    if (out !== d.drawer && drawer.current) {
      d.drawer = out;
      drawer.current.innerHTML = drawerMarkup(DRAWER_Z[1], out);
    }
    const press = fix(pressAt(s.pressT));
    if (press !== d.press && rod.current) {
      d.press = press;
      rod.current.setAttribute(
        "transform",
        translateAlong(P, [0, 0, -press * STAMP_TRAVEL]),
      );
    }
    const stamped = fix(s.stamped);
    if (stamped !== d.mark && mark.current) {
      d.mark = stamped;
      mark.current.style.opacity = String(stamped);
    }
  }, []);

  /* Advance the physics by dt seconds; calm jumps every part to where it would come to rest. */
  const step = useCallback(
    (dt: number, calm: boolean) => {
      const s = state.current;
      const index = activeRef.current;
      const target = STATION_X[index]!;
      if (calm) {
        s.x = target;
        s.v = 0;
      } else {
        const substeps = Math.max(1, Math.ceil(dt * 240));
        const h = dt / substeps;
        for (let i = 0; i < substeps; i++) {
          s.v += ((target - s.x) * STIFF - s.v * DRAG) * h;
          s.x += s.v * h;
        }
      }
      const arrived = Math.abs(s.x - target) < 1.5 && Math.abs(s.v) < 6;
      s.acts = s.acts.map((value, k) => {
        const goal = k === index && arrived ? 1 : 0;
        return calm ? goal : follow(value, goal, dt, 0.24);
      });
      s.scanT = s.acts[1]! > 0.01 ? s.scanT + dt : 0;
      if (index === 4 && arrived) {
        if (calm) s.pressT = 2;
        else s.pressT = s.pressT < 0 ? 0 : s.pressT + dt;
      } else s.pressT = -1;
      const markGoal =
        index === 4
          ? s.pressT >= 0.3
            ? 1
            : 0
          : index === 0
            ? 0
            : s.stamped > 0.5
              ? 1
              : 0;
      s.stamped = calm ? markGoal : follow(s.stamped, markGoal, dt, 0.12);
      draw();
    },
    [draw],
  );

  useEffect(() => {
    if (still) step(0, true);
  }, [active, still, step]);

  /* On narrow screens the bench is wider than its plate: keep the active station in view. */
  useEffect(() => {
    const node = pan.current;
    const svg = node?.querySelector("svg");
    if (!node || !svg || node.scrollWidth <= node.clientWidth + 1) return;
    const share = at([STATION_X[active], PRESS_Y, 0])[0] / WIDTH;
    node.scrollTo({
      left: share * svg.clientWidth - node.clientWidth / 2,
      behavior: still ? "auto" : "smooth",
    });
  }, [active, still]);

  useEffect(() => {
    if (!inView || still) return;
    let frame = 0;
    let last = 0;
    const tick = (now: number) => {
      const dt = last ? Math.min((now - last) / 1000, 1 / 30) : 1 / 60;
      last = now;
      const s = state.current;
      s.clock += dt;
      step(dt, false);
      if (!pausedRef.current && s.clock - touched.current > HANDS_OFF) {
        s.dwell += dt;
        if (s.dwell > DWELL[activeRef.current]!) {
          s.dwell = 0;
          setActive((current) => (current + 1) % stations.length);
        }
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [inView, still, step, stations.length]);

  const choose = (index: number) => {
    touched.current = state.current.clock;
    state.current.dwell = 0;
    setActive(index);
  };

  const onKey = (event: KeyboardEvent<HTMLOListElement>) => {
    const keys: Record<string, number> = {
      ArrowRight: 1,
      ArrowDown: 1,
      ArrowLeft: -1,
      ArrowUp: -1,
    };
    let next: number | undefined;
    if (event.key in keys)
      next = (active + keys[event.key]! + stations.length) % stations.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = stations.length - 1;
    if (next === undefined) return;
    event.preventDefault();
    choose(next);
    root.current
      ?.querySelectorAll<HTMLButtonElement>("[data-station]")
      [next]?.focus();
  };

  const onFigureClick = (event: MouseEvent<SVGSVGElement>) => {
    const part = (event.target as Element).closest("[data-part]");
    const index = part ? Number(part.getAttribute("data-part")) : NaN;
    if (Number.isInteger(index)) choose(index);
  };

  return (
    <div className="lp-rig" ref={root} data-active={active}>
      <div className="lp-rig-plate">
        <div className="lp-rig-corners" aria-hidden="true">
          <span data-corner="fig">Fig. 1</span>
          <span data-corner="title">The inspection bench</span>
          <span data-corner="hint">Select a station</span>
          <span data-corner="readout">
            {stations[active]!.step} · {stations[active]!.readout}
          </span>
        </div>
        {still ? null : (
          <button
            type="button"
            className="lp-rig-tour"
            aria-pressed={paused}
            onClick={() => setPaused((value) => !value)}
          >
            {paused ? "Play tour" : "Pause tour"}
          </button>
        )}
        <div className="lp-rig-scroll" ref={pan}>
          <svg
            className="iso-svg"
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            role="img"
            aria-label="An inspection bench. A pull request card rides a carriage along two rails past five stations: a card rack for the manifest change, a scanning head over your code, two release blocks on a comparator with a dial gauge, a card-index cabinet holding the upstream pull request, and a press that stamps the verdict on the card."
            focusable="false"
            onClick={onFigureClick}
          >
            {layers.base}
            {layers.rackBack}
            <g ref={rackCard}>{layers.rackCard}</g>
            {layers.rackFront}
            {layers.scanBack}
            {layers.compare}
            <g data-subject="2">
              <path
                ref={needlePath}
                className="iso-line lp-rig-needle"
                data-tone="hi"
                d={restNeedle}
              />
              <circle className="lp-rig-hub" cx={hub[0]} cy={hub[1]} r={0.9} />
            </g>
            {layers.cabinet}
            <g
              ref={drawer}
              data-part="3"
              dangerouslySetInnerHTML={{ __html: restDrawer }}
            />
            {layers.pressBack}
            {layers.rails}
            <g
              ref={carriage}
              transform={translateAlong(P, [STATION_X[0], 0, 0])}
            >
              {layers.carriage}
              <path
                ref={scan}
                className="iso-line lp-rig-scan"
                data-tone="lit"
                d=""
                style={{ opacity: 0 }}
              />
              <g ref={mark} style={{ opacity: 0 }}>
                {layers.mark}
              </g>
            </g>
            {layers.scanTop}
            <g ref={rod}>{layers.pressRod}</g>
            {layers.pressTop}
          </svg>
        </div>
      </div>
      <ol
        className="lp-rig-stations"
        aria-label="Stations on the bench"
        onKeyDown={onKey}
      >
        {stations.map((station, index) => (
          <li key={station.step}>
            <button
              type="button"
              data-station=""
              aria-pressed={index === active}
              tabIndex={index === active ? 0 : -1}
              onClick={() => choose(index)}
            >
              <span className="lp-rig-step">
                <span>{station.step}</span>
                {station.name}
              </span>
              <span className="lp-rig-title">{station.title}</span>
              <span className="lp-rig-body">{station.body}</span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
