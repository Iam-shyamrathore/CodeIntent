/** Paths for the parts that change shape while the bench runs; shipped to the client, so it stays small. */
import {
  lineOnTop,
  pathOf,
  slabOf,
  type Flat,
  type Plan,
  type SolidPaths,
  type Tone,
} from "../iso/iso-kit";
import {
  CABINET,
  CARD,
  CARD_H,
  CARRIAGE_TOP,
  DIAL,
  DRAWER_H,
  P,
  at,
} from "./view";

export const DRAWER_PLAN = {
  x: CABINET.x + 3,
  w: CABINET.w - 6,
  face: CABINET.y + CABINET.d,
};
export function drawerArt(z: number, out: number) {
  const depth = 2 + out;
  const box: Plan = {
    x: DRAWER_PLAN.x,
    y: DRAWER_PLAN.face,
    w: DRAWER_PLAN.w,
    d: depth,
    r: 0.8,
  };
  const front = DRAWER_PLAN.face + depth;
  return {
    box: slabOf(box, z, DRAWER_H, P, 2, 0.3),
    pull: slabOf(
      {
        x: DRAWER_PLAN.x + DRAWER_PLAN.w / 2 - 6,
        y: front,
        w: 12,
        d: 1.6,
        r: 0.6,
      },
      z + 3,
      2.6,
      P,
      2,
    ),
    label: pathOf(
      [
        at([DRAWER_PLAN.x + 5, front, z + DRAWER_H - 2]),
        at([DRAWER_PLAN.x + 14, front, z + DRAWER_H - 2]),
        at([DRAWER_PLAN.x + 14, front, z + DRAWER_H - 4.4]),
        at([DRAWER_PLAN.x + 5, front, z + DRAWER_H - 4.4]),
      ],
      true,
    ),
    index:
      out > 4
        ? slabOf(
            {
              x: DRAWER_PLAN.x + 8,
              y: DRAWER_PLAN.face + out - 4,
              w: DRAWER_PLAN.w - 16,
              d: 1.4,
              r: 0.3,
            },
            z + DRAWER_H,
            Math.min(7, out * 0.45),
            P,
            2,
          )
        : null,
  };
}

export const SCAN_SPAN = { from: CARD.y + 1.5, to: CARD.y + CARD.d - 1.5 };
export const scanLine = (y: number) =>
  lineOnTop(
    [CARD.x + 1, y],
    [CARD.x + CARD.w - 1, y],
    CARRIAGE_TOP + CARD_H + 0.05,
    P,
  );

/** The dial needle, angle in radians from the zero mark (0 points to -y, clockwise from above). */
export function needle(angle: number) {
  const z = DIAL.z + DIAL.h + 0.1;
  const from = -Math.PI * 0.75 + angle;
  const tip: Flat = at([
    DIAL.x + (DIAL.r - 2.4) * Math.sin(from),
    DIAL.y - (DIAL.r - 2.4) * Math.cos(from),
    z,
  ]);
  const tail: Flat = at([
    DIAL.x - 2 * Math.sin(from),
    DIAL.y + 2 * Math.cos(from),
    z,
  ]);
  return pathOf([tail, tip]);
}

/** The same markup as the server `Solid`, as a string for parts rebuilt each frame. */
export function solidMarkup(
  paths: SolidPaths,
  tone: Tone = "mid",
  crease = true,
) {
  const shades = paths.shades
    .map((d, shade) =>
      d ? `<path class="iso-shade" data-shade="${shade}" d="${d}"/>` : "",
    )
    .join("");
  const creaseLine =
    crease && paths.crease
      ? `<path class="iso-line iso-crease" data-tone="faint" d="${paths.crease}"/>`
      : "";
  return `<g class="iso-solid"><path class="iso-fill" d="${paths.fill}"/>${shades}<path class="iso-top" d="${paths.top}"/>${creaseLine}<path class="iso-line iso-edge" data-tone="${tone}" d="${paths.outline}"/></g>`;
}

export function drawerMarkup(z: number, out: number) {
  const art = drawerArt(z, out);
  return (
    solidMarkup(art.box, "mid", false) +
    `<path class="iso-line" data-tone="lo" d="${art.label}"/>` +
    solidMarkup(art.pull, "mid", false) +
    (art.index ? `<g data-subject="3">${solidMarkup(art.index, "hi")}</g>` : "")
  );
}
