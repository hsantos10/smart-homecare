import { MapPin, Clock } from "lucide-react";
import type { CurrentStatus } from "@/lib/types";
import { activityIcon, categoryStyle, riskStyle } from "@/lib/icons";
import { clockTime, durationLabel } from "@/lib/format";
import { cn } from "@/lib/utils";

export function StatusHero({ status }: { status: CurrentStatus }) {
  const Icon = activityIcon(status.activity_icon);
  const cat = categoryStyle[status.activity_category] ?? categoryStyle.unknown;
  const risk = riskStyle[status.risk_level];

  return (
    <section className={cn("rounded-2xl border p-5", cat.bg)}>
      <div className="flex items-center gap-4">
        <div className={cn("flex size-16 shrink-0 items-center justify-center rounded-2xl bg-background/70 shadow-sm", cat.fg)}>
          <Icon className="size-8" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Current activity
          </p>
          <h2 className="truncate text-2xl font-bold leading-tight text-foreground">
            {status.home ? status.activity_label : "Away from home"}
          </h2>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-sm text-muted-foreground">
            {status.current_zone && status.home && (
              <span className="flex items-center gap-1">
                <MapPin className="size-3.5" /> {status.current_zone}
              </span>
            )}
            {status.since && (
              <span className="flex items-center gap-1">
                <Clock className="size-3.5" /> since {clockTime(status.since)}
                {status.duration_minutes != null && status.duration_minutes > 0 && (
                  <span className="text-muted-foreground/70">· {durationLabel(status.duration_minutes)}</span>
                )}
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-2">
        <span className={cn("flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold", risk.bg, risk.fg)}>
          <span className={cn("size-2 rounded-full", risk.dot)} /> {risk.label}
        </span>
        {status.active_alerts > 0 && (
          <span className="rounded-full bg-red-50 px-2.5 py-1 text-xs font-semibold text-red-700 dark:bg-red-950/40 dark:text-red-300">
            {status.active_alerts} active alert{status.active_alerts > 1 ? "s" : ""}
          </span>
        )}
      </div>
    </section>
  );
}
