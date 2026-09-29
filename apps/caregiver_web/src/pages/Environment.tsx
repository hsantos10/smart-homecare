import { Thermometer, Droplets, Wind, Factory, Flame, FlaskConical } from "lucide-react";
import { api } from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import { Skeleton } from "@/components/ui/skeleton";
import type { EnvReading } from "@/lib/types";
import { cn } from "@/lib/utils";

type Tone = "ok" | "warn" | "alert";

// The server judges each reading against the profile's env_threshold rules (the same
// ones that raise alerts). The local bands below are only a fallback for kinds no rule covers.
function assess(r: EnvReading): { text: string; tone: Tone } {
  if (r.value == null) return { text: "—", tone: "ok" };
  if (r.status) {
    if (r.status === "ok") return { text: "Normal", tone: "ok" };
    return { text: r.status_text ?? "Out of range", tone: r.status };
  }
  if (r.kind === "temperature") {
    // Rule Book comfort band: 18–28 °C (65–82 °F). Pick thresholds by unit.
    const isF = r.unit.toUpperCase().includes("F");
    const [lo, hi] = isF ? [65, 82] : [18, 28];
    if (r.value < lo) return { text: "Too cold", tone: "warn" };
    if (r.value > hi) return { text: "Too warm", tone: "warn" };
    return { text: "Comfortable", tone: "ok" };
  }
  if (r.kind === "humidity") {
    if (r.value < 30) return { text: "Dry", tone: "warn" };
    if (r.value > 60) return { text: "Humid", tone: "warn" };
    return { text: "Comfortable", tone: "ok" };
  }
  if (r.kind === "co2") return r.value > 1000 ? { text: "Elevated", tone: "warn" } : { text: "Good", tone: "ok" };
  return { text: "", tone: "ok" };
}

const ICON = {
  temperature: Thermometer, humidity: Droplets, co2: Wind, pm25: Factory,
  co: Flame, voc: FlaskConical, other: Wind,
} as const;
const KIND_LABEL: Record<EnvReading["kind"], string> = {
  temperature: "Temperature", humidity: "Humidity", co2: "CO₂", pm25: "PM2.5",
  co: "Carbon monoxide", voc: "VOC index", other: "Other",
};
const TONE_CLASS: Record<Tone, string> = {
  ok: "text-emerald-600", warn: "text-amber-600", alert: "text-red-600",
};

export function Environment({ profileId }: { profileId: string }) {
  const { data, loading } = usePolling(() => api.environment(profileId), 15_000, [profileId]);

  // Group by area for a tidy layout.
  const byArea = new Map<string, EnvReading[]>();
  for (const r of data ?? []) {
    const k = r.area ?? "Other";
    (byArea.get(k) ?? byArea.set(k, []).get(k)!).push(r);
  }

  return (
    <div className="space-y-5 p-4">
      {loading && !data ? (
        <Skeleton className="h-40 w-full" />
      ) : byArea.size === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">No environmental sensors reporting.</p>
      ) : (
        [...byArea.entries()].map(([area, readings]) => (
          <section key={area}>
            <h3 className="mb-2 text-sm font-semibold">{area}</h3>
            <div className="grid grid-cols-2 gap-3">
              {readings.map((r) => {
                const Icon = ICON[r.kind] ?? Wind;
                const a = assess(r);
                return (
                  <div key={r.entity_id} className="rounded-xl border bg-card p-4">
                    <Icon className="size-5 text-cyan-500" />
                    <p className="mt-2 text-2xl font-bold">
                      {r.value ?? "—"}<span className="ml-1 text-sm font-normal text-muted-foreground">{r.unit}</span>
                    </p>
                    <p className="text-xs text-muted-foreground">{KIND_LABEL[r.kind] ?? r.kind}</p>
                    {a.text && (
                      <p className={cn("mt-0.5 text-xs font-medium", TONE_CLASS[a.tone])}>
                        {a.text}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        ))
      )}

    </div>
  );
}
