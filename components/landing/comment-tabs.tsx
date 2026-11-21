"use client";

import {
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

export function CommentTabs({
  labels,
  panels,
}: {
  labels: string[];
  panels: ReactNode[];
}) {
  const [active, setActive] = useState(0);
  const id = useId();
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const move =
      event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!move) return;
    event.preventDefault();
    const next = (active + move + labels.length) % labels.length;
    setActive(next);
    tabs.current[next]?.focus();
  };
  return (
    <div className="lp-tabs">
      <div
        className="lp-tablist"
        role="tablist"
        aria-label="Example comments"
        onKeyDown={onKey}
      >
        {labels.map((label, index) => (
          <button
            key={label}
            ref={(node) => {
              tabs.current[index] = node;
            }}
            type="button"
            role="tab"
            id={`${id}-tab-${index}`}
            aria-selected={index === active}
            aria-controls={`${id}-panel-${index}`}
            tabIndex={index === active ? 0 : -1}
            onClick={() => setActive(index)}
          >
            {label}
          </button>
        ))}
      </div>
      {panels.map((panel, index) => (
        <div
          key={index}
          role="tabpanel"
          id={`${id}-panel-${index}`}
          aria-labelledby={`${id}-tab-${index}`}
          hidden={index !== active}
          className="lp-tabpanel"
        >
          {panel}
        </div>
      ))}
    </div>
  );
}
