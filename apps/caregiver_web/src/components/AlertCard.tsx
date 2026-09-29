import { AlertTriangle, Check, Phone, Video } from "lucide-react";
import type { Alert } from "@/lib/types";
import { severityColor } from "@/lib/icons";
import { clockTime, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export function AlertCard({
  alert,
  onAck,
  prominent = false,
}: {
  alert: Alert;
  onAck?: (id: string) => void;
  prominent?: boolean;
}) {
  const critical = alert.severity === "CRITICAL";

  if (prominent && critical) {
    // Red hero card (matches the "FALL DETECTED" mockup).
    return (
      <div className="rounded-2xl bg-red-600 p-5 text-white shadow-lg">
        <div className="flex items-start gap-3">
          <AlertTriangle className="size-7 shrink-0" />
          <div className="flex-1">
            <p className="text-lg font-bold leading-tight">{alert.rule_name}</p>
            <p className="text-sm text-white/90">
              {alert.zone ? `${alert.zone} · ` : ""}{clockTime(alert.timestamp)}
            </p>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-2">
          <Button variant="secondary" className="bg-white text-red-700 hover:bg-white/90">
            <Video className="size-4" /> View camera
          </Button>
          <Button variant="secondary" className="bg-white text-red-700 hover:bg-white/90">
            <Phone className="size-4" /> Call now
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-3 rounded-xl border bg-card p-4">
      <span className={cn("mt-1 size-2.5 shrink-0 rounded-full", severityColor[alert.severity] ?? "bg-neutral-400")} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-semibold leading-tight">{alert.rule_name}</p>
          <span className="shrink-0 text-xs text-muted-foreground">{timeAgo(alert.timestamp)}</span>
        </div>
        <p className="mt-0.5 text-sm text-muted-foreground">{alert.message}</p>
        {!alert.acknowledged && onAck && (
          <Button
            size="sm"
            variant="outline"
            className="mt-2 h-7 text-xs"
            onClick={() => onAck(alert.id)}
          >
            <Check className="size-3.5" /> Acknowledge
          </Button>
        )}
        {alert.acknowledged && (
          <span className="mt-2 inline-flex items-center gap-1 text-xs text-emerald-600">
            <Check className="size-3.5" /> Acknowledged
          </span>
        )}
      </div>
    </div>
  );
}
