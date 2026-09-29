import { useEffect, useState } from "react";
import { Watch, CheckCircle, AlertCircle, RefreshCw, Save } from "lucide-react";
import { api } from "@/lib/api";
import type { HAEntity } from "@/lib/types";

const WATCH_KEYS: { key: string; label: string; domain: "sensor" | "binary_sensor"; hint: string }[] = [
  { key: "heart_rate",       label: "Heart Rate",       domain: "sensor",        hint: "bpm" },
  { key: "steps_today",      label: "Steps Today",      domain: "sensor",        hint: "steps" },
  { key: "battery_level",    label: "Battery Level",    domain: "sensor",        hint: "%" },
  { key: "battery_state",    label: "Battery State",    domain: "sensor",        hint: "charging/discharging" },
  { key: "on_body",          label: "On Body",          domain: "binary_sensor", hint: "on/off" },
  { key: "activity_state",   label: "Activity State",   domain: "sensor",        hint: "active/passive" },
  { key: "calories",         label: "Calories",         domain: "sensor",        hint: "cal" },
  { key: "distance",         label: "Distance",         domain: "sensor",        hint: "ft or m" },
  { key: "phone_activity",   label: "Phone Activity",   domain: "sensor",        hint: "still/walking" },
  { key: "sleep_confidence", label: "Sleep Confidence", domain: "sensor",        hint: "%" },
];

function liveLabel(eid: string, entities: HAEntity[]): string {
  const e = entities.find((x) => x.entity_id === eid);
  if (!e) return "—";
  const age = e.last_changed
    ? Math.round((Date.now() - new Date(e.last_changed).getTime()) / 60_000)
    : null;
  const ageStr = age != null ? (age < 60 ? ` · ${age}m ago` : ` · ${Math.floor(age / 60)}h ago`) : "";
  return `${e.state}${e.unit ? " " + e.unit : ""}${ageStr}`;
}

interface Props {
  profileId: string;
}

export function WatchConfigAdmin({ profileId }: Props) {
  const [config, setConfig] = useState<Record<string, string>>({});
  const [entities, setEntities] = useState<HAEntity[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [cfg, sensorEnts, binEnts] = await Promise.all([
        api.watchConfig(profileId),
        api.haEntities("sensor"),
        api.haEntities("binary_sensor"),
      ]);
      setConfig(cfg);
      setEntities([...sensorEnts, ...binEnts]);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [profileId]);

  function setKey(key: string, value: string) {
    setConfig((c) => ({ ...c, [key]: value }));
    setSaved(false);
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api.putWatchConfig(profileId, config);
      setSaved(true);
    } catch (e) {
      setError(`Save failed: ${e}`);
    } finally {
      setSaving(false);
    }
  }

  const sensorOptions = entities.filter((e) => e.domain === "sensor");
  const binaryOptions = entities.filter((e) => e.domain === "binary_sensor");

  function options(domain: "sensor" | "binary_sensor") {
    return domain === "sensor" ? sensorOptions : binaryOptions;
  }

  if (loading) {
    return (
      <div className="flex h-40 items-center justify-center text-muted-foreground text-sm">
        Loading HA entities…
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="flex size-10 items-center justify-center rounded-xl bg-sky-100 text-sky-600 dark:bg-sky-950/50">
            <Watch className="size-5" />
          </span>
          <div>
            <h2 className="text-lg font-semibold">Watch Entity Mapping</h2>
            <p className="text-sm text-muted-foreground">
              Link each health metric to its HA Companion App entity.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            className="flex items-center gap-1.5 rounded-lg border bg-background px-3 py-1.5 text-sm font-medium hover:bg-muted transition-colors"
          >
            <RefreshCw className="size-3.5" />
            Refresh HA
          </button>
          <button
            onClick={save}
            disabled={saving}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
          >
            <Save className="size-3.5" />
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-400">
          <AlertCircle className="size-4 shrink-0" />
          {error}
        </div>
      )}

      {saved && (
        <div className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-400">
          <CheckCircle className="size-4 shrink-0" />
          Watch config saved to profile YAML.
        </div>
      )}

      {/* Mapping table */}
      <div className="rounded-2xl border bg-card overflow-hidden">
        <div className="grid grid-cols-[160px_1fr_160px] gap-0 border-b bg-muted/50 px-4 py-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          <span>Metric</span>
          <span>HA Entity</span>
          <span>Live Value</span>
        </div>
        {WATCH_KEYS.map(({ key, label, domain, hint }, i) => {
          const saved_eid = config[key] ?? "";
          const opts = options(domain);
          const liveVal = saved_eid ? liveLabel(saved_eid, entities) : "—";
          const isSet = !!saved_eid && entities.some((e) => e.entity_id === saved_eid);

          return (
            <div
              key={key}
              className={`grid grid-cols-[160px_1fr_160px] items-center gap-4 px-4 py-3 ${
                i < WATCH_KEYS.length - 1 ? "border-b" : ""
              }`}
            >
              <div>
                <p className="text-sm font-medium">{label}</p>
                <p className="text-xs text-muted-foreground">{hint}</p>
              </div>

              <div className="flex items-center gap-2">
                {isSet ? (
                  <CheckCircle className="size-3.5 shrink-0 text-emerald-500" />
                ) : (
                  <div className="size-3.5 shrink-0 rounded-full border-2 border-muted" />
                )}
                <select
                  value={saved_eid}
                  onChange={(e) => setKey(key, e.target.value)}
                  className="w-full rounded-lg border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  <option value="">— not set —</option>
                  {opts.map((ent) => (
                    <option key={ent.entity_id} value={ent.entity_id}>
                      {ent.friendly_name} ({ent.entity_id})
                    </option>
                  ))}
                </select>
              </div>

              <p className="text-sm text-muted-foreground tabular-nums">{liveVal}</p>
            </div>
          );
        })}
      </div>

      {/* Quick test summary */}
      <div className="rounded-2xl border bg-card p-4">
        <p className="mb-3 text-sm font-semibold">Quick Test — All Current Values</p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
          {WATCH_KEYS.map(({ key, label }) => {
            const eid = config[key] ?? "";
            const val = eid ? liveLabel(eid, entities) : "—";
            return (
              <div key={key} className="rounded-xl border bg-muted/30 p-3">
                <p className="text-xs text-muted-foreground">{label}</p>
                <p className="mt-0.5 text-sm font-semibold">{val}</p>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
