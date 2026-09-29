import { ChevronRight } from "lucide-react";
import { api } from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import { StatusHero } from "@/components/StatusHero";
import { FloorMap } from "@/components/FloorMap";
import { AlertCard } from "@/components/AlertCard";
import { CareModeCard } from "@/components/CareMode";
import { activityIcon, categoryStyle } from "@/lib/icons";
import { timeAgo } from "@/lib/format";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { TabKey } from "@/components/BottomNav";
import type { CareMode, CareModeKey } from "@/lib/types";

export function Summary({ profileId, onNavigate, patientName, careMode, setCareMode }: {
  profileId: string;
  onNavigate: (t: TabKey) => void;
  patientName: string;
  careMode?: CareMode;
  setCareMode: (m: CareModeKey, minutes: number | null) => Promise<void>;
}) {
  const { data: status } = usePolling(() => api.currentStatus(profileId), 5_000, [profileId]);
  const { data: alerts } = usePolling(() => api.alerts(profileId, { acknowledged: false, limit: 10 }), 5_000, [profileId]);
  const { data: recent } = usePolling(() => api.activityLog(profileId, { limit: 5 }), 10_000, [profileId]);

  const critical = alerts?.find((a) => a.severity === "CRITICAL");
  const others = (alerts ?? []).filter((a) => a.id !== critical?.id);

  return (
    <div className="space-y-5 p-4">
      {!status ? (
        <Skeleton className="h-36 w-full rounded-2xl" />
      ) : critical ? (
        <AlertCard alert={critical} prominent />
      ) : (
        <StatusHero status={status} />
      )}

      {others.length > 0 && (
        <div className="grid gap-2">
          {others.slice(0, 2).map((a) => (
            <AlertCard key={a.id} alert={a} />
          ))}
        </div>
      )}

      <CareModeCard profileId={profileId} patientName={patientName}
                    mode={careMode} setMode={setCareMode} />

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold">Home overview</h3>
        </div>
        <FloorMap presence={status?.presence_by_zone ?? {}} />
      </section>

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold">Recent activity</h3>
          <button onClick={() => onNavigate("activity")} className="flex items-center text-xs font-medium text-primary">
            See all <ChevronRight className="size-3.5" />
          </button>
        </div>
        <div className="divide-y rounded-xl border bg-card">
          {!recent
            ? Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="m-3 h-10" />)
            : recent.map((e) => {
                const Icon = activityIcon(e.icon);
                const cat = categoryStyle[e.category] ?? categoryStyle.unknown;
                return (
                  <div key={e.id} className="flex items-center gap-3 px-4 py-3">
                    <span className={cn("flex size-9 items-center justify-center rounded-full", cat.bg, cat.fg)}>
                      <Icon className="size-[18px]" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className={cn("truncate text-sm font-medium", e.severity === "warning" && "text-red-600 dark:text-red-400")}>
                        {e.label}
                      </p>
                      <p className="truncate text-xs text-muted-foreground">{e.zone ?? "—"}</p>
                    </div>
                    <span className="shrink-0 text-xs text-muted-foreground">{timeAgo(e.timestamp)}</span>
                  </div>
                );
              })}
        </div>
      </section>
    </div>
  );
}
