import { Dots, Line, Solid } from "../iso/draw";
import {
  BASE_ART,
  CABINET_ART,
  CARRIAGE_ART,
  COMPARE_ART,
  DRAWERS,
  PRESS_ART,
  RACK_ART,
  RACK_LIT,
  RAIL_ART,
  SCAN_ART,
  STAMP_MARK,
} from "./geometry";
import { drawerArt, drawerMarkup, needle } from "./frame";
import { RigLive } from "./live";
import { STATIONS } from "./stations";

const BASE = (
  <g key="base">
    <path className="iso-halo" d={BASE_ART.halo} />
    {BASE_ART.feet.map((parts, index) => (
      <g key={index}>
        {parts.map((paths, part) => (
          <Solid key={part} paths={paths} tone={part ? "mid" : "lo"} />
        ))}
      </g>
    ))}
    <Solid paths={BASE_ART.slab} tone="mid" />
    <Line d={BASE_ART.groove} tone="lo" />
    <Line d={BASE_ART.screwRings} tone="lo" />
    <Dots points={BASE_ART.screws} tone="mid" />
    <Solid paths={BASE_ART.ruler} tone="lo" crease="none" />
    <Line d={BASE_ART.ticksMinor} tone="lo" />
    <Line d={BASE_ART.ticksMajor} tone="mid" />
    <Solid paths={BASE_ART.label} tone="lo" crease="none" />
    <Line d={BASE_ART.labelLine} tone="faint" />
    <Line d={BASE_ART.labelRule} tone="lo" />
    <Dots points={BASE_ART.labelScrews} size={0.45} tone="mid" />
  </g>
);

const RACK_BACK = (
  <g key="rack-back" data-part="0">
    <Solid paths={RACK_ART.base} tone="mid" />
    <Line d={RACK_ART.slots} tone="lo" />
    <Dots points={RACK_ART.screws} size={0.45} tone="mid" />
    {RACK_ART.cards.slice(0, RACK_LIT).map((paths, index) => (
      <Solid key={index} paths={paths} tone="mid" />
    ))}
  </g>
);

const RACK_CARD = (
  <g key="rack-card" data-subject="0">
    <Solid paths={RACK_ART.cards[RACK_LIT]!} tone="hi" />
  </g>
);

const RACK_FRONT = (
  <g key="rack-front" data-part="0">
    {RACK_ART.cards.slice(RACK_LIT + 1).map((paths, index) => (
      <Solid key={index} paths={paths} tone="mid" />
    ))}
    <Solid paths={RACK_ART.knob} tone="mid" />
    <Line d={RACK_ART.knobKnurl} tone="lo" />
  </g>
);

const SCAN_BACK = (
  <g key="scan-back" data-part="1">
    <Solid paths={SCAN_ART.foot} tone="lo" />
    <Dots points={SCAN_ART.footScrews} size={0.45} tone="mid" />
    <Solid
      paths={SCAN_ART.column}
      tone="mid"
      crease="none"
      inner={<Line d={SCAN_ART.columnSeams} tone="faint" />}
    />
    <Solid paths={SCAN_ART.collar} tone="mid" />
    <Solid paths={SCAN_ART.thumb} tone="mid" crease="none" />
    <Solid paths={SCAN_ART.thumbKnob} tone="mid" />
  </g>
);

const SCAN_TOP = (
  <g key="scan-top" data-part="1">
    <Solid paths={SCAN_ART.lens} tone="mid" />
    <g data-subject="1">
      <Solid
        paths={SCAN_ART.head}
        tone="hi"
        inner={<Line d={SCAN_ART.headVent} tone="lo" />}
      />
    </g>
    <Solid paths={SCAN_ART.arm} tone="mid" />
    <Dots points={SCAN_ART.armScrews} size={0.5} tone="mid" />
  </g>
);

const COMPARE = (
  <g key="compare" data-part="2">
    <Solid paths={COMPARE_ART.plate} tone="lo" />
    <Dots points={COMPARE_ART.plateScrews} size={0.45} tone="mid" />
    <Solid paths={COMPARE_ART.stem} tone="mid" crease="none" />
    {COMPARE_ART.pedestals.map((paths, index) => (
      <Solid key={index} paths={paths} tone="mid" />
    ))}
    <Line d={COMPARE_ART.pedestalRings} tone="faint" />
    <Solid paths={COMPARE_ART.before} tone="mid" />
    <g data-subject="2">
      <Solid paths={COMPARE_ART.beforeTab} tone="hi" />
    </g>
    <Solid paths={COMPARE_ART.after} tone="mid" />
    <Line d={COMPARE_ART.afterSeat} tone="lo" />
    <Solid paths={COMPARE_ART.dial} tone="mid" />
    <Line d={COMPARE_ART.bezel} tone="lo" />
    <Line d={COMPARE_ART.ticksMinor} tone="lo" />
    <Line d={COMPARE_ART.ticksMajor} tone="mid" />
  </g>
);

const REST_DRAWER = (z: number) => {
  const art = drawerArt(z, 0);
  return (
    <g key={`drawer-${z}`}>
      <Solid paths={art.box} tone="mid" crease="none" />
      <Line d={art.label} tone="lo" />
      <Solid paths={art.pull} tone="mid" crease="none" />
    </g>
  );
};

const CABINET = (
  <g key="cabinet" data-part="3">
    <Solid paths={CABINET_ART.plinth} tone="lo" />
    <Solid
      paths={CABINET_ART.body}
      tone="mid"
      inner={<Line d={CABINET_ART.seams} tone="faint" />}
    />
    <Dots points={CABINET_ART.topScrews} size={0.45} tone="mid" />
    {REST_DRAWER(DRAWERS[0])}
    {REST_DRAWER(DRAWERS[2])}
  </g>
);

const PRESS_BACK = (
  <g key="press-back" data-part="4">
    <Solid paths={PRESS_ART.foot} tone="lo" />
    <Dots points={PRESS_ART.footScrews} size={0.45} tone="mid" />
    <Solid
      paths={PRESS_ART.column}
      tone="mid"
      crease="none"
      inner={<Line d={PRESS_ART.columnSeams} tone="faint" />}
    />
    <Solid paths={PRESS_ART.collar} tone="mid" />
  </g>
);

const PRESS_ROD = (
  <g key="press-rod" data-subject="4">
    <Solid paths={PRESS_ART.rod} tone="mid" crease="none" />
    <Solid
      paths={PRESS_ART.head}
      tone="hi"
      inner={<Line d={PRESS_ART.headRing} tone="faint" />}
    />
  </g>
);

const PRESS_TOP = (
  <g key="press-top" data-part="4">
    <Solid
      paths={PRESS_ART.housing}
      tone="mid"
      inner={<Line d={PRESS_ART.housingSeams} tone="faint" />}
    />
    <Line d={PRESS_ART.gland} tone="lo" />
    <Solid paths={PRESS_ART.arm} tone="mid" />
    <Dots points={PRESS_ART.armScrews} size={0.5} tone="mid" />
    <Solid paths={PRESS_ART.cap} tone="mid" />
    <Line d={PRESS_ART.capKnurl} tone="lo" />
  </g>
);

const RAILS = (
  <g key="rails">
    {RAIL_ART.rails.map((paths, index) => (
      <Solid key={index} paths={paths} tone="mid" />
    ))}
    <Dots points={RAIL_ART.railScrews} size={0.45} tone="mid" />
    {RAIL_ART.stops.map((paths, index) => (
      <Solid key={index} paths={paths} tone="mid" />
    ))}
    <Dots points={RAIL_ART.stopScrews} size={0.45} tone="mid" />
  </g>
);

const CARRIAGE = (
  <g key="carriage">
    <path className="iso-halo iso-halo-small" d={CARRIAGE_ART.halo} />
    {CARRIAGE_ART.bushings.map((paths, index) => (
      <Solid key={index} paths={paths} tone="lo" />
    ))}
    <Solid paths={CARRIAGE_ART.plate} tone="mid" />
    <Dots points={CARRIAGE_ART.plateScrews} size={0.45} tone="mid" />
    <Solid paths={CARRIAGE_ART.card} tone="hi" />
    <Line d={CARRIAGE_ART.cardLines} tone="lo" />
    <Solid paths={CARRIAGE_ART.cardTab} tone="lo" crease="none" />
  </g>
);

const MARK = (
  <g key="mark">
    <Line d={STAMP_MARK.frame} tone="red" />
    <Line d={STAMP_MARK.bars} tone="red" />
  </g>
);

export function RigArt() {
  return (
    <RigLive
      stations={STATIONS}
      layers={{
        base: BASE,
        rackBack: RACK_BACK,
        rackCard: RACK_CARD,
        rackFront: RACK_FRONT,
        scanBack: SCAN_BACK,
        scanTop: SCAN_TOP,
        compare: COMPARE,
        cabinet: CABINET,
        pressBack: PRESS_BACK,
        pressRod: PRESS_ROD,
        pressTop: PRESS_TOP,
        rails: RAILS,
        carriage: CARRIAGE,
        mark: MARK,
      }}
      restNeedle={needle(0)}
      restDrawer={drawerMarkup(DRAWERS[1], 0)}
      hub={COMPARE_ART.hub}
    />
  );
}
