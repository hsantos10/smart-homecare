import {
  Heart, Footprints, BatteryMedium, BatteryCharging, BatteryFull,
  Watch, Activity, Flame, MapPin, Phone, Moon,
} from "lucide-react";
import { api } from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import type { HealthData } from "@/lib/types";

const PROFILE_ID = "patient-001";

function BatteryIcon({ state }: { state: string | null }) {
  if (state === "charging") return <BatteryCharging className="size-5 text-emerald-500" />;
  if (state === "full") return <BatteryFull className="size-5 text-emerald-500" />;
  return <BatteryMedium className="size-5 text-sky-500" />;
}

function MetricCard({
  icon: Icon,
  iconClass,
  label,
  value,
  unit,
  sub,
}: {
  icon: React.ElementType;
  iconClass: string;
  label: string;
  value: string | number | null;
  unit?: string;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border bg-card p-4">
      <Icon className={`size-5 ${iconClass}`} />
      <p className="mt-2 text-2xl font-bold leading-none">
        {value ?? "—"}
        {value != null && unit && (
          <span className="ml-1 text-sm font-normal text-muted-foreground">{unit}</span>
        )}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">{label}</p>
      {sub && <p className="mt-0.5 text-[10px] text-muted-foreground/70">{sub}</p>}
    </div>
  );
}

function formatDistance(dist: number | null, unit: string): string {
  if (dist == null) return "—";
  if (unit.toLowerCase().includes("ft")) {
    const miles = dist / 5280;
    return miles >= 0.1 ? `${miles.toFixed(1)} mi` : `${Math.round(dist)} ft`;
  }
  const km = dist / 1000;
  return km >= 0.1 ? `${km.toFixed(1)} km` : `${Math.round(dist)} m`;
}

function capitalise(s: string | null) {
  if (!s) return null;
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function activityLabel(state: string | null, phone: string | null): string | null {
  const v = state ?? phone;
  if (!v) return null;
  return v.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function lastUpdatedLabel(iso: string | null): string {
  if (!iso) return "";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  return `${Math.floor(mins / 60)}h ago`;
}

export function Health() {
  const { data } = usePolling<HealthData>(
    () => api.health(PROFILE_ID),
    15_000,
    [],
  );

  const h = data;
  const distStr = formatDistance(h?.distance ?? null, h?.distance_unit ?? "ft");

  return (
    <div className="space-y-4 p-4">
      {/* Watch status bar */}
      <div className="flex items-center gap-3 rounded-2xl border bg-card p-4">
        <span
          className={`flex size-11 items-center justify-center rounded-xl ${
            h?.connected
              ? "bg-emerald-50 text-emerald-600 dark:bg-emerald-950/50"
              : "bg-muted text-muted-foreground"
          }`}
        >
          <Watch className="size-6" />
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold">{h?.watch_name ?? "Pixel Watch"}</p>
          <p className="text-xs text-muted-foreground">
            {h?.connected ? (
              <>
                On body · Battery {h.battery_level}%
                {h.last_updated && (
                  <> · Updated {lastUpdatedLabel(h.last_updated)}</>
                )}
              </>
            ) : (
              "Not detected on body"
            )}
          </p>
        </div>
        {h && <BatteryIcon state={h.battery_state} />}
      </div>

      {/* Primary metrics — heart rate + steps */}
      <div className="grid grid-cols-2 gap-3">
        <MetricCard
          icon={Heart}
          iconClass="text-rose-500"
          label="Heart rate"
          value={h?.heart_rate != null ? Math.round(h.heart_rate) : null}
          unit={h?.heart_rate_unit ?? "bpm"}
        />
        <MetricCard
          icon={Footprints}
          iconClass="text-emerald-500"
          label="Steps today"
          value={h?.steps_today != null ? h.steps_today.toLocaleString() : null}
          unit="steps"
        />
        <MetricCard
          icon={Flame}
          iconClass="text-orange-500"
          label="Calories"
          value={h?.calories != null ? Math.round(h.calories).toLocaleString() : null}
          unit="cal"
        />
        <MetricCard
          icon={MapPin}
          iconClass="text-violet-500"
          label="Distance"
          value={h ? distStr : null}
        />
      </div>

      {/* Secondary metrics */}
      <div className="grid grid-cols-2 gap-3">
        <MetricCard
          icon={Activity}
          iconClass="text-sky-500"
          label="Activity state"
          value={activityLabel(h?.activity_state ?? null, h?.phone_activity ?? null)}
        />
        <MetricCard
          icon={Moon}
          iconClass="text-indigo-400"
          label="Sleep confidence"
          value={h?.sleep_confidence != null ? Math.round(h.sleep_confidence) : null}
          unit="%"
          sub="from phone sensor"
        />
        <MetricCard
          icon={Phone}
          iconClass="text-slate-500"
          label="Phone activity"
          value={capitalise(h?.phone_activity ?? null)}
        />
        <MetricCard
          icon={Watch}
          iconClass="text-sky-500"
          label="Watch battery"
          value={h?.battery_level ?? null}
          unit="%"
          sub={capitalise(h?.battery_state ?? null) ?? undefined}
        />
      </div>

      <p className="px-1 text-center text-xs text-muted-foreground">
        Health data streams from the patient's smartwatch via HA Companion App.
        Fall detection uses ceiling sensors — watch fall alerts coming soon.
      </p>
    </div>
  );
}
