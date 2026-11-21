import {
  corners,
  cylinder,
  depthOf,
  insetPlan,
  lineOnTop,
  pathOf,
  planOutline,
  radialTicks,
  ring,
  segment,
  sideArc,
  slabOf,
  topTicks,
  knurl,
  type Flat,
  type Plan,
  type Plane,
} from "../iso/iso-kit";
import {
  BASE,
  BASE_H,
  CABINET,
  CABINET_H,
  CABINET_Z,
  CARD,
  CARD_H,
  CARRIAGE,
  CARRIAGE_H,
  CARRIAGE_TOP,
  CARRIAGE_Z,
  DIAL,
  DRAWER_H,
  DRAWER_Z,
  FOOT_H,
  HEAD_Z,
  P,
  PRESS_TOP,
  PRESS_Y,
  RAIL_D,
  RAIL_FROM,
  RAIL_H,
  RAIL_TO,
  RAIL_Y,
  SCAN_TOP,
  STATION_X,
  at,
} from "./view";

const slab = (plan: Plan, z: number, h: number, steps = 4, bevel = 0) =>
  slabOf(plan, z, h, P, steps, bevel);
const round = (cx: number, cy: number, r: number, z: number, h: number) =>
  cylinder(cx, cy, r, z, h, P, 28);
const join = (paths: string[]) => paths.filter(Boolean).join("");
const byDepth = (points: Plane[]) =>
  [...points].sort(
    (a, b) => depthOf([a[0], a[1], 0], P) - depthOf([b[0], b[1], 0], P),
  );
const dotsAt = (points: Plane[], z: number): Flat[] =>
  points.map(([x, y]) => at([x, y, z]));
const ruleLines = (plan: Plan, z: number, rows: number, gap: number) =>
  join(
    Array.from({ length: rows }, (_, row) =>
      lineOnTop(
        [plan.x + 3, plan.y + 3 + row * gap],
        [plan.x + plan.w - (row % 2 ? 12 : 5), plan.y + 3 + row * gap],
        z,
        P,
      ),
    ),
  );

/* Base plate on four feet, with a groove, corner screws, a ruler strip and a label plate. */
const FEET = byDepth(corners(BASE, 24));
const SCREWS = corners(BASE, 9);
const RULER: Plan = { x: -118, y: BASE.y + BASE.d - 14, w: 306, d: 6, r: 1 };
const LABEL: Plan = { x: -192, y: BASE.y + BASE.d - 17, w: 62, d: 11, r: 1.5 };
const TICKS = topTicks(
  RULER.x + 3,
  RULER.x + RULER.w - 3,
  4,
  5,
  RULER.y + 0.6,
  0.6,
  [1.8, 3.4],
  P,
);

export const BASE_ART = {
  halo: slab(BASE, -BASE_H - FOOT_H, BASE_H + FOOT_H, 8).fill,
  feet: FEET.map(([x, y]) => [
    round(x, y, 7.5, -BASE_H - FOOT_H, 1.6),
    round(x, y, 5.6, -BASE_H - FOOT_H + 1.6, FOOT_H - 1.6),
  ]),
  slab: slab(BASE, -BASE_H, BASE_H, 8, 1.6),
  groove: planOutline(insetPlan(BASE, 5), 0, P),
  screwRings: join(SCREWS.map(([x, y]) => ring(x, y, 2.2, 0, P, 16))),
  screws: dotsAt(SCREWS, 0),
  ruler: slab(RULER, 0, 0.6, 3),
  ticksMinor: TICKS.minor,
  ticksMajor: TICKS.major,
  label: slab(LABEL, 0, 0.8, 3),
  labelLine: planOutline(insetPlan(LABEL, 1.5), 0.8, P),
  labelRule: join(
    [0, 1, 2].map((row) =>
      lineOnTop(
        [LABEL.x + 8, LABEL.y + 3.2 + row * 2.3],
        [LABEL.x + (row === 1 ? 36 : 50), LABEL.y + 3.2 + row * 2.3],
        0.8,
        P,
      ),
    ),
  ),
  labelScrews: dotsAt(
    [
      [LABEL.x + 3.6, LABEL.y + LABEL.d / 2],
      [LABEL.x + LABEL.w - 3.6, LABEL.y + LABEL.d / 2],
    ],
    0.8,
  ),
};

/* Two guide rails with end stops. */
const STOPS: Plan[] = [RAIL_FROM - 4, RAIL_TO - 2].map((x) => ({
  x,
  y: RAIL_Y[0] - 3,
  w: 6,
  d: RAIL_Y[1] - RAIL_Y[0] + RAIL_D + 6,
  r: 1.2,
}));
export const RAIL_ART = {
  rails: RAIL_Y.map((y) =>
    slab(
      { x: RAIL_FROM, y, w: RAIL_TO - RAIL_FROM, d: RAIL_D, r: 1 },
      0,
      RAIL_H,
      3,
      0.4,
    ),
  ),
  railScrews: dotsAt(
    RAIL_Y.flatMap((y) =>
      [-120, -40, 40, 120].map((x) => [x, y + RAIL_D / 2] as Plane),
    ),
    RAIL_H,
  ),
  stops: STOPS.map((plan) => slab(plan, 0, 8, 3, 0.5)),
  stopScrews: dotsAt(
    STOPS.flatMap((plan) => [
      [plan.x + 3, plan.y + 3] as Plane,
      [plan.x + 3, plan.y + plan.d - 3] as Plane,
    ]),
    8,
  ),
};

/* The carriage, with the pull request card on it, built at x = 0. */
const BUSHINGS: Plan[] = [-25, 15].flatMap((x) =>
  RAIL_Y.map((y) => ({ x, y: y - 2.5, w: 10, d: RAIL_D + 5, r: 1.2 })),
);
export const CARRIAGE_ART = {
  halo: slab(CARRIAGE, 0, CARRIAGE_TOP, 4).fill,
  bushings: byDepthPlans(BUSHINGS).map((plan) =>
    slab(plan, 0.6, CARRIAGE_Z + CARRIAGE_H - 0.6, 3, 0.4),
  ),
  plate: slab(CARRIAGE, CARRIAGE_Z, CARRIAGE_H, 5, 0.6),
  plateScrews: dotsAt(corners(CARRIAGE, 3.4), CARRIAGE_TOP),
  card: slab(CARD, CARRIAGE_TOP, CARD_H, 3, 0.4),
  cardLines: ruleLines(insetPlan(CARD, 1), CARRIAGE_TOP + CARD_H, 4, 3.2),
  cardTab: slab(
    { x: CARD.x + 2, y: CARD.y + CARD.d - 7, w: 10, d: 5, r: 0.8 },
    CARRIAGE_TOP + CARD_H,
    0.5,
    2,
  ),
};

function byDepthPlans(plans: Plan[]) {
  return [...plans].sort(
    (a, b) =>
      depthOf([a.x + a.w / 2, a.y + a.d / 2, 0], P) -
      depthOf([b.x + b.w / 2, b.y + b.d / 2, 0], P),
  );
}

/* Station 1, the manifest: a card rack whose third card is the line that changed. */
const S1 = STATION_X[0];
const RACK: Plan = { x: S1 - 25, y: -54, w: 50, d: 36, r: 3 };
const RACK_SLOTS = [-48, -40, -32, -24];
export const RACK_ART = {
  base: slab(RACK, 0, 9, 4, 0.8),
  slots: join(
    RACK_SLOTS.map((y) =>
      planOutline({ x: S1 - 21, y: y - 0.4, w: 42, d: 2.4, r: 0.6 }, 9, P, 2),
    ),
  ),
  screws: dotsAt(corners(RACK, 3.4), 9),
  cards: RACK_SLOTS.map((y, index) =>
    slab(
      { x: S1 - 19, y, w: 38, d: 1.6, r: 0.4 },
      9,
      [26, 23, 21, 17][index]!,
      2,
    ),
  ),
  knob: round(S1 + 29.5, -36, 3.2, 0, 6),
  knobKnurl: knurl(S1 + 29.5, -36, 3.2, 0, 6, 18, P),
};
export const RACK_LIT = 2;

/* Station 2, the usage scan: a column, an arm over the rail and a scan head with a lens. */
const S2 = STATION_X[1];
const SCAN_Y = -40;
const SCAN_ARM: Plan = {
  x: S2 - 5,
  y: SCAN_Y - 6,
  w: 10,
  d: PRESS_Y + 6 - SCAN_Y + 4,
  r: 2,
};
export const SCAN_ART = {
  foot: slab({ x: S2 - 12, y: SCAN_Y - 12, w: 24, d: 24, r: 3 }, 0, 3, 4, 0.6),
  footScrews: dotsAt(
    corners({ x: S2 - 12, y: SCAN_Y - 12, w: 24, d: 24, r: 3 }, 3),
    3,
  ),
  column: round(S2, SCAN_Y, 4.6, 3, SCAN_TOP - 3),
  columnSeams: join([14, 30].map((z) => sideArc(S2, SCAN_Y, 4.6, z, P, 16))),
  collar: round(S2, SCAN_Y, 6.6, 36, 5),
  thumb: slab({ x: S2 + 6, y: SCAN_Y - 1.6, w: 4, d: 3.2, r: 0.6 }, 37, 3, 2),
  thumbKnob: round(S2 + 11.5, SCAN_Y, 2.4, 36.4, 4.2),
  arm: slab(SCAN_ARM, SCAN_TOP, 7, 3, 0.6),
  armScrews: dotsAt(
    [
      [S2, SCAN_Y],
      [S2, PRESS_Y],
    ],
    SCAN_TOP + 7,
  ),
  head: slab(
    { x: S2 - 8, y: PRESS_Y - 7, w: 16, d: 14, r: 2 },
    44,
    SCAN_TOP - 44,
    4,
    0.6,
  ),
  headVent: join(
    [48, 51, 54].map((z) =>
      segment([S2 - 8 + 3, PRESS_Y + 7, z], [S2 + 8 - 3, PRESS_Y + 7, z], P),
    ),
  ),
  lens: round(S2, PRESS_Y, 3.6, 41, 3),
};

/* Station 3, the releases: two specimen blocks on pedestals, and a dial gauge between them. */
const S3 = STATION_X[2];
const BENCH3: Plan = { x: S3 - 36, y: -58, w: 72, d: 48, r: 3 };
const SPEC = [
  { x: S3 - 19, y: -44 },
  { x: S3 + 19, y: -44 },
];
const BLOCK = (x: number, y: number): Plan => ({
  x: x - 7,
  y: y - 7,
  w: 14,
  d: 14,
  r: 1.5,
});
const TAB = (x: number, y: number): Plan => ({
  x: x - 3,
  y: y - 3,
  w: 6,
  d: 6,
  r: 0.8,
});
const DIAL_TICKS = radialTicks(
  DIAL.x,
  DIAL.y,
  DIAL.r - 1.6,
  24,
  6,
  DIAL.z + DIAL.h,
  [1.2, 2.4],
  P,
  -Math.PI * 0.75,
  Math.PI * 1.5,
);
export const COMPARE_ART = {
  plate: slab(BENCH3, 0, 3, 5, 0.6),
  plateScrews: dotsAt(corners(BENCH3, 3.4), 3),
  pedestals: SPEC.map(({ x, y }) => round(x, y, 8.5, 3, 5)),
  pedestalRings: join(SPEC.map(({ x, y }) => ring(x, y, 7, 8, P, 28))),
  before: slab(BLOCK(SPEC[0]!.x, SPEC[0]!.y), 8, 17, 3, 0.6),
  beforeTab: slab(TAB(SPEC[0]!.x, SPEC[0]!.y), 25, 4.5, 2, 0.3),
  after: slab(BLOCK(SPEC[1]!.x, SPEC[1]!.y), 8, 17, 3, 0.6),
  afterSeat: planOutline(TAB(SPEC[1]!.x, SPEC[1]!.y), 25, P, 2),
  dial: round(DIAL.x, DIAL.y, DIAL.r, DIAL.z, DIAL.h),
  bezel: ring(DIAL.x, DIAL.y, DIAL.r - 0.9, DIAL.z + DIAL.h, P, 36),
  ticksMinor: DIAL_TICKS.minor,
  ticksMajor: DIAL_TICKS.major,
  hub: at([DIAL.x, DIAL.y, DIAL.z + DIAL.h]),
  stem: slab(
    { x: DIAL.x - 1.4, y: DIAL.y - DIAL.r - 4, w: 2.8, d: 4.4, r: 0.6 },
    4.2,
    3,
    2,
  ),
};

/* Station 4, the upstream record: a card-index cabinet; the middle drawer opens. */
export const CABINET_ART = {
  plinth: slab(insetPlan(CABINET, -2.5), 0, CABINET_Z, 4, 0.6),
  body: slab(CABINET, CABINET_Z, CABINET_H, 4, 0.8),
  topScrews: dotsAt(corners(CABINET, 3), CABINET_Z + CABINET_H),
  seams: join(
    [16.5, 28.5].map((z) =>
      segment(
        [CABINET.x + CABINET.w, CABINET.y + 2, z],
        [CABINET.x + CABINET.w, CABINET.y + CABINET.d - 2, z],
        P,
      ),
    ),
  ),
};
export const DRAWERS = DRAWER_Z;

/* Station 5, the verdict: a press with a stamp that comes down on the card. */
const S5 = STATION_X[4];
const PRESS_COL_Y = -42;
const PRESS_ARM: Plan = {
  x: S5 - 6,
  y: PRESS_COL_Y - 7,
  w: 12,
  d: PRESS_Y - PRESS_COL_Y + 15,
  r: 2,
};
export const PRESS_ART = {
  foot: slab(
    { x: S5 - 13, y: PRESS_COL_Y - 13, w: 26, d: 26, r: 3 },
    0,
    3,
    4,
    0.6,
  ),
  footScrews: dotsAt(
    corners({ x: S5 - 13, y: PRESS_COL_Y - 13, w: 26, d: 26, r: 3 }, 3),
    3,
  ),
  column: round(S5, PRESS_COL_Y, 5.4, 3, PRESS_TOP - 3),
  columnSeams: join(
    [16, 34, 52].map((z) => sideArc(S5, PRESS_COL_Y, 5.4, z, P, 16)),
  ),
  collar: round(S5, PRESS_COL_Y, 7.6, 46, 5),
  arm: slab(PRESS_ARM, PRESS_TOP, 8, 3, 0.6),
  armScrews: dotsAt(
    [
      [S5 - 3, PRESS_Y + 2],
      [S5 + 3, PRESS_Y + 2],
    ],
    PRESS_TOP + 8,
  ),
  housing: round(S5, PRESS_Y, 7, 44, PRESS_TOP - 44),
  housingSeams: join([50, 62].map((z) => sideArc(S5, PRESS_Y, 7, z, P, 20))),
  gland: ring(S5, PRESS_Y, 4, 44, P, 20),
  cap: round(S5, PRESS_COL_Y, 4.2, PRESS_TOP + 8, 3.4),
  capKnurl: knurl(S5, PRESS_COL_Y, 4.2, PRESS_TOP + 8, PRESS_TOP + 11.4, 22, P),
  rod: round(S5, PRESS_Y, 2.6, HEAD_Z + 4, 40),
  head: round(S5, PRESS_Y, 8, HEAD_Z, 4),
  headRing: sideArc(S5, PRESS_Y, 8, HEAD_Z + 2, P, 24),
};

/** The mark the stamp leaves on the card: a framed verdict block. */
const MARK: Plan = { x: -6, y: 17, w: 16, d: 16, r: 1 };
export const STAMP_MARK = {
  frame: planOutline(MARK, CARRIAGE_TOP + CARD_H, P, 2),
  bars: join(
    [0, 1, 2].map((row) =>
      lineOnTop(
        [MARK.x + 3, MARK.y + 4 + row * 4],
        [MARK.x + MARK.w - 3 - (row === 1 ? 4 : 0), MARK.y + 4 + row * 4],
        CARRIAGE_TOP + CARD_H,
        P,
      ),
    ),
  ),
};
