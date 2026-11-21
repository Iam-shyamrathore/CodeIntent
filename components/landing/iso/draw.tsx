// Server-safe drawing primitives from the "anatomy" kit (MIT License, Copyright (c) 2026 Ryan).
import type * as React from "react";
import type { Flat, LineTone, SolidPaths, Tone } from "./iso-kit";

interface SolidProps {
  paths: SolidPaths;
  tone?: Tone;
  crease?: Tone | "none";
  halo?: boolean;
  lit?: boolean;
  flat?: boolean;
  className?: string;
  inner?: React.ReactNode;
  part?: string;
}

export function Solid({
  paths,
  tone = "hi",
  crease = "faint",
  halo = false,
  lit = false,
  flat = false,
  className,
  inner,
  part,
}: SolidProps) {
  return (
    <g
      className={className ? `iso-solid ${className}` : "iso-solid"}
      data-lit={lit ? "" : undefined}
      data-part={part}
    >
      {halo ? <path className="iso-halo" d={paths.fill} /> : null}
      <path className="iso-fill" d={paths.fill} />
      {flat
        ? null
        : paths.shades.map((d, shade) =>
            d ? (
              <path
                key={shade}
                className="iso-shade"
                data-shade={shade}
                d={d}
              />
            ) : null,
          )}
      {flat ? null : <path className="iso-top" d={paths.top} />}
      {crease === "none" || !paths.crease ? null : (
        <path
          className="iso-line iso-crease"
          data-tone={crease}
          d={paths.crease}
        />
      )}
      {crease === "none" || !paths.bevel ? null : (
        <path
          className="iso-line iso-bevel"
          data-tone={crease}
          d={paths.bevel}
        />
      )}
      {inner}
      <path className="iso-line iso-edge" data-tone={tone} d={paths.outline} />
    </g>
  );
}

export function Line({
  d,
  tone = "lo",
  className,
}: {
  d: string;
  tone?: LineTone;
  className?: string;
}) {
  if (!d) return null;
  return (
    <path
      className={className ? `iso-line ${className}` : "iso-line"}
      data-tone={tone}
      d={d}
    />
  );
}

const tenth = (value: number) => Math.round(value * 10) / 10;

export function Dots({
  points,
  size = 0.5,
  tone = "mid",
}: {
  points: Flat[];
  size?: number;
  tone?: Tone;
}) {
  return (
    <g className="iso-dots" data-tone={tone}>
      {points.map(([x, y], index) => (
        <circle key={index} cx={tenth(x)} cy={tenth(y)} r={size} />
      ))}
    </g>
  );
}
