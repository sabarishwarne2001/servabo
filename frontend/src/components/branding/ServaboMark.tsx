import React, { useId } from "react";

import { DOT, ORBIT, RIBBON_STOPS, S_STROKE, S_WIDTH, TILE, TILE_COLOURS } from "../../../../brand/mark";

interface ServaboMarkProps {
  className?: string;
  /** Accessible name. Empty when the mark sits next to the word "servabo" (decorative). */
  title?: string;
  /** Draw the navy tile behind the mark (default). Leave it off on a surface that is already dark. */
  tile?: boolean;
}

/**
 * The Servabo mark: a glossy ribbon "S" with a thin orbit ring and a glowing dot (brand/mark.ts, the same
 * geometry the website and the favicons use). It is drawn in its own colours on a navy tile, so it reads
 * the same on a light or a dark page and for every tenant's colour scheme.
 */
export const ServaboMark: React.FC<ServaboMarkProps> = ({ className = "", title = "", tile = true }) => {
  // Gradient ids must be unique per drawing: a hidden copy of the mark would otherwise take the paint with it.
  const uid = `sv${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  return (
    <svg
      viewBox="0 0 32 32"
      className={className}
      role={title ? "img" : undefined}
      aria-label={title || undefined}
      aria-hidden={title ? undefined : true}
      focusable="false"
      data-servabo-mark=""
    >
      <defs>
        <linearGradient id={`${uid}-r`} gradientUnits="userSpaceOnUse" x1="11" y1="8" x2="22" y2="26">
          {RIBBON_STOPS.map(([offset, colour]) => (
            <stop key={offset} offset={offset} stopColor={colour} />
          ))}
        </linearGradient>
        <linearGradient id={`${uid}-o`} gradientUnits="userSpaceOnUse" x1="2" y1="22" x2="30" y2="10">
          <stop offset="0" stopColor="#8b5cf6" stopOpacity="0.15" />
          <stop offset="0.55" stopColor="#3b82f6" />
          <stop offset="1" stopColor="#2ee6f2" />
        </linearGradient>
        <linearGradient id={`${uid}-t`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={TILE_COLOURS[0]} />
          <stop offset="1" stopColor={TILE_COLOURS[1]} />
        </linearGradient>
        <radialGradient id={`${uid}-g`}>
          <stop offset="0" stopColor="#7df3ff" stopOpacity="0.95" />
          <stop offset="1" stopColor="#2ee6f2" stopOpacity="0" />
        </radialGradient>
      </defs>
      {tile ? <path d={TILE} fill={`url(#${uid}-t)`} /> : null}
      <ellipse
        cx={ORBIT.cx}
        cy={ORBIT.cy}
        rx={ORBIT.rx}
        ry={ORBIT.ry}
        transform={`rotate(${ORBIT.rot} ${ORBIT.cx} ${ORBIT.cy})`}
        fill="none"
        stroke={`url(#${uid}-o)`}
        strokeWidth={ORBIT.width}
      />
      <path d={S_STROKE} fill="none" stroke={`url(#${uid}-r)`} strokeWidth={S_WIDTH} strokeLinecap="round" strokeLinejoin="round" />
      <path
        d={S_STROKE}
        fill="none"
        stroke="#fff"
        strokeOpacity={0.38}
        strokeWidth={0.9}
        strokeLinecap="round"
        strokeLinejoin="round"
        transform="translate(-0.8 -0.9)"
      />
      <circle cx={DOT.x} cy={DOT.y} r={DOT.r * 2.3} fill={`url(#${uid}-g)`} />
      <circle cx={DOT.x} cy={DOT.y} r={DOT.r} fill="#fff" />
    </svg>
  );
};

export default ServaboMark;
