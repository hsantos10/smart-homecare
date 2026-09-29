import { User } from "lucide-react";
import { cn } from "@/lib/utils";
import { FLOORPLAN_URL as floorplanUrl, CANVAS, ROOMS } from "@/lib/floorplan";

export function FloorMap({
  presence,
  className,
}: {
  presence: Record<string, boolean>;
  className?: string;
}) {
  // Case-insensitive lookup so "Living room" matches whatever HA returns.
  const occ = (name: string) =>
    Object.entries(presence).some(([k, v]) => v && k.toLowerCase() === name.toLowerCase());

  return (
    <div className={cn("relative w-full overflow-hidden rounded-xl border bg-muted/30", className)}>
      <svg
        viewBox={`0 0 ${CANVAS.width} ${CANVAS.height}`}
        className="block w-full"
        role="img"
        aria-label="Home floor plan"
      >
        <image href={floorplanUrl} x={0} y={0} width={CANVAS.width} height={CANVAS.height} />
        {ROOMS.map((r) => {
          const isOcc = occ(r.name);
          const cx = (r.x0 + r.x1) / 2;
          const cy = (r.y0 + r.y1) / 2;
          return (
            <g key={r.name}>
              <rect
                x={r.x0}
                y={r.y0}
                width={r.x1 - r.x0}
                height={r.y1 - r.y0}
                rx={6}
                className={cn(
                  "transition-colors",
                  isOcc ? "fill-emerald-500/12 stroke-emerald-500" : "fill-transparent stroke-transparent",
                )}
                strokeWidth={3}
              />
              <text
                x={cx}
                y={r.y0 + 22}
                textAnchor="middle"
                dominantBaseline="middle"
                className="fill-foreground/70"
                style={{ fontSize: 20, fontWeight: 700, paintOrder: "stroke", stroke: "white", strokeWidth: 4 }}
              >
                {r.name}
              </text>
              {isOcc && (
                <g>
                  <circle cx={cx} cy={cy + 14} r={26} className="fill-emerald-500/25" />
                  <circle cx={cx} cy={cy + 14} r={13} className="fill-emerald-500 stroke-white" strokeWidth={3} />
                </g>
              )}
            </g>
          );
        })}
      </svg>
      <div className="absolute right-2 top-2 flex items-center gap-1 rounded-full bg-background/80 px-2 py-0.5 text-[10px] font-medium text-muted-foreground backdrop-blur">
        <span className="size-1.5 rounded-full bg-emerald-500" /> Live
      </div>
      {!Object.values(presence).some(Boolean) && (
        <div className="absolute inset-x-0 bottom-2 flex justify-center">
          <span className="flex items-center gap-1 rounded-full bg-background/80 px-2 py-1 text-[10px] text-muted-foreground backdrop-blur">
            <User className="size-3" /> No presence detected
          </span>
        </div>
      )}
    </div>
  );
}
