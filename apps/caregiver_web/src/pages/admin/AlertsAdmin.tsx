import { useState } from "react";
import { CheckCheck, RefreshCw, AlertTriangle, ShieldAlert, Info } from "lucide-react";
import { api } from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import type { Alert } from "@/lib/types";

const PROFILE_ID = "patient-001";

const SEV_COLORS: Record<string, string> = {
  CRITICAL: "bg-red-100 text-red-700 border-red-200 dark:bg-red-950/40 dark:text-red-400 dark:border-red-900",
  HIGH:     "bg-orange-100 text-orange-700 border-orange-200 dark:bg-orange-950/40 dark:text-orange-400 dark:border-orange-900",
  MEDIUM:   "bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-400 dark:border-amber-900",
  LOW:      "bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-400 dark:border-emerald-900",
};

const SEV_ICON: Record<string, React.ElementType> = {
  CRITICAL: AlertTriangle,
  HIGH:     ShieldAlert,
  MEDIUM:   ShieldAlert,
  LOW:      Info,
};

type AckFilter = "all" | "unacknowledged" | "acknowledged";

function fmtTs(ts: string) {
  try {
    return new Date(ts).toLocaleString(undefined, {
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return ts.slice(0, 16).replace("T", " ");
  }
}

export function AlertsAdmin({ profileId = PROFILE_ID }: { profileId?: string }) {
  const [catFilter, setCatFilter]   = useState("All");
  const [sevFilter, setSevFilter]   = useState("All");
  const [ackFilter, setAckFilter]   = useState<AckFilter>("all");
  const [acking, setAcking]         = useState<Set<string>>(new Set());
  const [refreshKey, setRefreshKey] = useState(0);

  const ackOpt: { value: AckFilter; label: string }[] = [
    { value: "all",            label: "All" },
    { value: "unacknowledged", label: "Unacknowledged" },
    { value: "acknowledged",   label: "Acknowledged" },
  ];

  const { data: alerts = [], loading } = usePolling(
    () => api.alerts(profileId, {
      acknowledged: ackFilter === "all" ? undefined : ackFilter === "acknowledged",
      limit: 200,
    }),
    30_000,
    [ackFilter, refreshKey],
  );

  const filtered = alerts.filter((a) => {
    if (catFilter !== "All" && a.category !== catFilter) return false;
    if (sevFilter !== "All" && a.severity !== sevFilter) return false;
    return true;
  });

  async function handleAck(id: string) {
    setAcking((s) => new Set(s).add(id));
    await api.acknowledgeAlert(id);
    setAcking((s) => { const n = new Set(s); n.delete(id); return n; });
    setRefreshKey((k) => k + 1);
  }

  const categories = ["All", ...Array.from(new Set(alerts.map((a) => a.category)))];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Alert History</h2>
          <p className="text-sm text-muted-foreground">
            {filtered.length} alert{filtered.length !== 1 ? "s" : ""} shown
          </p>
        </div>
        <button
          onClick={() => setRefreshKey((k) => k + 1)}
          className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm hover:bg-muted transition-colors"
        >
          <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">Category</label>
          <select
            value={catFilter}
            onChange={(e) => setCatFilter(e.target.value)}
            className="rounded-lg border bg-background px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          >
            {categories.map((c) => <option key={c}>{c}</option>)}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">Severity</label>
          <select
            value={sevFilter}
            onChange={(e) => setSevFilter(e.target.value)}
            className="rounded-lg border bg-background px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          >
            {["All", "CRITICAL", "HIGH", "MEDIUM", "LOW"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">Status</label>
          <div className="flex rounded-lg border overflow-hidden text-sm">
            {ackOpt.map(({ value, label }) => (
              <button
                key={value}
                onClick={() => setAckFilter(value)}
                className={`px-3 py-1.5 transition-colors ${
                  ackFilter === value
                    ? "bg-primary text-primary-foreground"
                    : "bg-background hover:bg-muted"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* List */}
      {filtered.length === 0 ? (
        <div className="rounded-xl border bg-muted/30 p-8 text-center text-sm text-muted-foreground">
          No alerts match the current filters.
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((alert) => <AlertRow key={alert.id} alert={alert} onAck={handleAck} acking={acking.has(alert.id)} />)}
        </div>
      )}
    </div>
  );
}

function AlertRow({ alert, onAck, acking }: { alert: Alert; onAck: (id: string) => void; acking: boolean }) {
  const Icon = SEV_ICON[alert.severity] ?? ShieldAlert;
  const colors = SEV_COLORS[alert.severity] ?? SEV_COLORS.LOW;

  return (
    <div className={`flex items-start gap-3 rounded-xl border p-3.5 ${colors}`}>
      <Icon className="size-4 shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium text-sm">{alert.rule_name}</span>
          <span className="text-xs opacity-70">{alert.category}</span>
          {alert.zone && (
            <span className="text-xs opacity-70">· {alert.zone}</span>
          )}
        </div>
        <p className="text-sm mt-0.5 opacity-90">{alert.message}</p>
        <p className="text-xs mt-1 opacity-60">{fmtTs(alert.timestamp)} UTC</p>
      </div>
      <div className="shrink-0">
        {alert.acknowledged ? (
          <span className="flex items-center gap-1 text-xs opacity-60">
            <CheckCheck className="size-3.5" /> Done
          </span>
        ) : (
          <button
            onClick={() => onAck(alert.id)}
            disabled={acking}
            className="flex items-center gap-1 rounded-lg border border-current/30 bg-white/40 dark:bg-black/20 px-2.5 py-1 text-xs font-medium hover:bg-white/60 transition-colors disabled:opacity-50"
          >
            <CheckCheck className="size-3.5" />
            {acking ? "..." : "Ack"}
          </button>
        )}
      </div>
    </div>
  );
}
