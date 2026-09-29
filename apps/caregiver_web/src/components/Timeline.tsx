import type { ActivityEvent } from "@/lib/types";
import { activityIcon, categoryStyle } from "@/lib/icons";
import { clockTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export function Timeline({ events }: { events: ActivityEvent[] }) {
  if (events.length === 0) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        No activity recorded yet.
      </p>
    );
  }
  return (
    <ol className="relative">
      {events.map((e, i) => {
        const Icon = activityIcon(e.icon);
        const cat = categoryStyle[e.category] ?? categoryStyle.unknown;
        const isWarning = e.severity === "warning";
        return (
          <li key={e.id} className="flex gap-3">
            {/* time + rail */}
            <div className="flex w-16 shrink-0 flex-col items-end pt-1.5">
              <span className="text-xs font-medium tabular-nums text-muted-foreground">
                {clockTime(e.timestamp)}
              </span>
            </div>
            <div className="relative flex flex-col items-center">
              <span className={cn("z-10 flex size-9 items-center justify-center rounded-full", cat.bg, cat.fg)}>
                <Icon className="size-[18px]" />
              </span>
              {i < events.length - 1 && <span className="w-px flex-1 bg-border" />}
            </div>
            {/* content */}
            <div className={cn("mb-4 flex-1 pt-1", isWarning && "rounded-lg")}>
              <p className={cn("text-sm font-semibold leading-tight", isWarning ? "text-red-600 dark:text-red-400" : "text-foreground")}>
                {e.label}
              </p>
              <p className="text-xs text-muted-foreground">
                {[e.zone, e.detail].filter(Boolean).join(" · ") || "—"}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
