import {
  boxCorners,
  fitProjection,
  iso,
  type Plan,
  type Point3,
} from "../iso/iso-kit";

/** World layout of the inspection bench, in units of about 1 px; x runs along the bench, z is up. */
export const WIDTH = 760;
export const HEIGHT = 380;
export const AZIMUTH = 60;

export const BASE: Plan = { x: -206, y: -72, w: 412, d: 136, r: 9 };
export const BASE_H = 10;
export const FOOT_H = 5;

export const RAIL_Y = [12, 32] as const;
export const RAIL_D = 5;
export const RAIL_H = 3;
export const RAIL_FROM = -192;
export const RAIL_TO = 192;

/** The pull request rides on this carriage, built at x = 0 and moved along x. */
export const CARRIAGE: Plan = { x: -25, y: 8, w: 50, d: 34, r: 3 };
export const CARRIAGE_Z = RAIL_H;
export const CARRIAGE_H = 5;
export const CARRIAGE_TOP = CARRIAGE_Z + CARRIAGE_H;
export const CARD: Plan = { x: -19, y: 13, w: 38, d: 24, r: 1.5 };
export const CARD_H = 1.6;
export const CARD_TOP = CARRIAGE_TOP + CARD_H;

/** Station centres along the bench: manifest, usage, releases, upstream, verdict. */
export const STATION_X = [-160, -80, 0, 80, 160] as const;

export const SCAN_TOP = 61;
export const PRESS_TOP = 69;
export const PRESS_Y = 25;
export const HEAD_Z = 26;
export const STAMP_TRAVEL = HEAD_Z - CARD_TOP;
export const DIAL = { x: 0, y: -22, r: 9.5, z: 3, h: 6 };
export const CABINET: Plan = { x: 57, y: -58, w: 46, d: 40, r: 2 };
export const CABINET_Z = 3;
export const CABINET_H = 42;
export const DRAWER_Z = [8, 20, 32] as const;
export const DRAWER_H = 9;
export const DRAWER_OUT = 16;

export const P = fitProjection(
  [
    ...boxCorners(BASE, -BASE_H - FOOT_H, 0),
    ...boxCorners(
      { x: STATION_X[4] - 8, y: -48, w: 16, d: 72, r: 0 },
      0,
      PRESS_TOP + 8,
    ),
    ...boxCorners(
      { x: STATION_X[1] - 6, y: -46, w: 12, d: 70, r: 0 },
      0,
      SCAN_TOP + 7,
    ),
  ],
  WIDTH,
  HEIGHT,
  { pad: 30, azimuth: AZIMUTH },
);

export const at = (point: Point3) => iso(point, P);
