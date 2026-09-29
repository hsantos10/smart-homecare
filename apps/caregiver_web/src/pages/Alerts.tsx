import { useState } from "react";
import { BellOff } from "lucide-react";
import { api } from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import { AlertCard } from "@/components/AlertCard";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export function Alerts({ profileId }: { profileId: string }) {
  const [filter, setFilter] = useState<"active" | "all">("active");
  const [acking, setAcking] = useState<Set<string>>(new Set());
  const { data, loading } = usePolling(
    () => api.alerts(profileId, filter === "active" ? { acknowledged: false, limit: 50 } : { limit: 50 }),
    8_000,
    [profileId, filter],
  );

  const handleAck = async (id: string) => {
    setAcking((s) => new Set(s).add(id));
    await api.acknowledgeAlert(id);
  };

  const alerts = (data ?? []).filter((a) => !acking.has(a.id) || filter === "all");

  return (
    <div className="space-y-4 p-4">
      <div className="flex gap-2">
        {(["active", "all"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={cn(
              "rounded-full px-3 py-1.5 text-xs font-medium capitalize transition-colors",
              filter === f ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
            )}
          >
            {f}
          </button>
        ))}
      </div>

      {loading && !data ? (
        <div className="space-y-3">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-20" />)}</div>
      ) : alerts.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-16 text-center text-muted-foreground">
          <BellOff className="size-8" />
          <p className="text-sm">{filter === "active" ? "No active alerts" : "No alerts"}</p>
        </div>
      ) : (
        <div className="space-y-3">
          {alerts.map((a) => (
            <AlertCard key={a.id} alert={a} onAck={handleAck} />
          ))}
        </div>
      )}
    </div>
  );
}
