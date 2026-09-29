import { useState, useEffect } from "react";
import {
  Plus, Pencil, Trash2, ToggleLeft, ToggleRight, ChevronDown, ChevronUp,
  ShieldAlert, Activity, Thermometer, HeartPulse, X, Save,
} from "lucide-react";
import { api } from "@/lib/api";
import type { CareModeKey, Rule } from "@/lib/types";

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: "bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-400",
  HIGH:     "bg-orange-100 text-orange-700 dark:bg-orange-950/40 dark:text-orange-400",
  MEDIUM:   "bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400",
  LOW:      "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400",
};

const TRIGGER_LABELS: Record<string, string> = {
  fall:              "Fall Detected",
  door_opened:       "Door Opened",
  room_inactivity:   "Room Inactivity",
  global_inactivity: "Global Inactivity",
  night_wandering:   "Night Wandering",
  long_stay:         "Long Stay",
  sensor_threshold:  "Sensor Threshold",
  env_threshold:     "Environment Threshold",
  vital_threshold:   "Health Threshold (watch)",
};

const ENV_METRICS: Record<string, string> = {
  temperature: "Temperature", humidity: "Humidity (%)", co2: "CO₂ (ppm)",
  pm25: "PM2.5 (µg/m³)", co: "Carbon monoxide (ppm)", voc: "VOC index",
};
const VITAL_METRICS: Record<string, string> = { heart_rate: "Heart rate (bpm)" };
const OP_SYMBOL: Record<string, string> = { gt: ">", gte: "≥", lt: "<", lte: "≤" };

/** "co2 > 1000 for 5 min" — the one-line summary shown in the rule list. */
function conditionText(r: Omit<Rule, "id">): string | null {
  if (!r.operator || r.value == null) return null;
  const what = r.metric
    ? (ENV_METRICS[r.metric] ?? VITAL_METRICS[r.metric] ?? r.metric).replace(/ \(.*\)$/, "")
    : "value";
  return `${what} ${OP_SYMBOL[r.operator] ?? r.operator} ${r.value}${r.unit ? ` ${r.unit}` : ""}`;
}

const CATEGORY_ICON: Record<string, React.ElementType> = {
  Safety:      ShieldAlert,
  Activity:    Activity,
  Environment: Thermometer,
  Health:      HeartPulse,
};

const EMPTY_RULE: Omit<Rule, "id"> = {
  name: "", enabled: true, category: "Safety", severity: "MEDIUM",
  trigger_type: "fall", message: "", zone: null, entity_id: null,
  duration_minutes: null, no_return_minutes: null, operator: null,
  value: null, metric: null, unit: null, time_window: null, cooldown_minutes: 10,
};

const num = (v: string) => (v.trim() === "" || isNaN(Number(v)) ? null : Number(v));

/** Condition + threshold + "must hold for" — shared by the three threshold triggers. */
function ThresholdFields({ form, set }: { form: Omit<Rule, "id">; set: (k: keyof Omit<Rule, "id">, v: unknown) => void }) {
  return (
    <>
      <div>
        <label className="label">Condition</label>
        <select className="input w-full" value={form.operator ?? "gt"} onChange={(e) => set("operator", e.target.value)}>
          <option value="gt">Above (&gt;)</option>
          <option value="gte">At or above (≥)</option>
          <option value="lt">Below (&lt;)</option>
          <option value="lte">At or below (≤)</option>
        </select>
      </div>
      <div>
        <label className="label">Threshold value</label>
        <input type="number" className="input w-full" value={form.value ?? ""} onChange={(e) => set("value", num(e.target.value))} />
      </div>
      <div>
        <label className="label">Must hold for (min)</label>
        <input type="number" min={0} className="input w-full" value={form.duration_minutes ?? ""} placeholder="0 = immediately" onChange={(e) => set("duration_minutes", num(e.target.value))} />
      </div>
    </>
  );
}

interface EditorProps {
  initial: Omit<Rule, "id">;
  onSave: (r: Omit<Rule, "id">) => void;
  onCancel: () => void;
}

function RuleEditor({ initial, onSave, onCancel }: EditorProps) {
  const [form, setForm] = useState<Omit<Rule, "id">>(initial);
  const set = (k: keyof typeof form, v: unknown) =>
    setForm((f) => ({ ...f, [k]: v }));

  const useTW = !!form.time_window;

  return (
    <div className="space-y-4 rounded-2xl border bg-card p-6">
      <h3 className="font-semibold text-base">
        {initial.name ? `Edit: ${initial.name}` : "New Rule"}
      </h3>

      {/* Row 1 */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <label className="label">Rule name</label>
          <input
            className="input w-full"
            value={form.name}
            onChange={(e) => set("name", e.target.value)}
            placeholder="e.g. Long bathroom stay"
          />
        </div>
        <div>
          <label className="label">Category</label>
          <select className="input w-full" value={form.category} onChange={(e) => set("category", e.target.value)}>
            {["Safety", "Activity", "Environment", "Health"].map((c) => <option key={c}>{c}</option>)}
          </select>
        </div>
        <div>
          <label className="label">Severity</label>
          <select className="input w-full" value={form.severity} onChange={(e) => set("severity", e.target.value)}>
            {["CRITICAL", "HIGH", "MEDIUM", "LOW"].map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className="label">Trigger type</label>
          <select className="input w-full" value={form.trigger_type} onChange={(e) => set("trigger_type", e.target.value)}>
            {Object.entries(TRIGGER_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        <div>
          <label className="label">Cooldown (min)</label>
          <input
            type="number" min={1} className="input w-full"
            value={form.cooldown_minutes}
            onChange={(e) => set("cooldown_minutes", parseInt(e.target.value) || 10)}
          />
        </div>
      </div>

      {/* Trigger-specific fields */}
      {(form.trigger_type === "room_inactivity" || form.trigger_type === "long_stay") && (
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">Room / zone</label>
            <input className="input w-full" value={form.zone ?? ""} onChange={(e) => set("zone", e.target.value || null)} placeholder="e.g. Bedroom Bathroom" />
          </div>
          <div>
            <label className="label">Duration (min)</label>
            <input type="number" min={1} className="input w-full" value={form.duration_minutes ?? ""} onChange={(e) => set("duration_minutes", parseInt(e.target.value) || null)} />
          </div>
        </div>
      )}
      {form.trigger_type === "door_opened" && (
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">Door entity_id</label>
            <input className="input w-full" value={form.entity_id ?? ""} onChange={(e) => set("entity_id", e.target.value || null)} placeholder="binary_sensor.front_door" />
          </div>
          <div>
            <label className="label">No-return timeout (min)</label>
            <input type="number" min={0} className="input w-full" value={form.no_return_minutes ?? 0} onChange={(e) => set("no_return_minutes", parseInt(e.target.value) || null)} />
          </div>
        </div>
      )}
      {form.trigger_type === "global_inactivity" && (
        <div className="w-48">
          <label className="label">Inactivity duration (min)</label>
          <input type="number" min={15} className="input w-full" value={form.duration_minutes ?? 120} onChange={(e) => set("duration_minutes", parseInt(e.target.value) || null)} />
        </div>
      )}
      {form.trigger_type === "fall" && (
        <div>
          <label className="label">Fall entity_id (optional)</label>
          <input className="input w-full" value={form.entity_id ?? ""} onChange={(e) => set("entity_id", e.target.value || null)} placeholder="blank = every entity HA reports as a fall sensor" />
        </div>
      )}
      {form.trigger_type === "sensor_threshold" && (
        <div className="grid grid-cols-3 gap-3">
          <div className="col-span-3">
            <label className="label">Sensor entity_id</label>
            <input className="input w-full" value={form.entity_id ?? ""} onChange={(e) => set("entity_id", e.target.value || null)} placeholder="sensor.kitchen_plug_power" />
          </div>
          <ThresholdFields form={form} set={set} />
        </div>
      )}
      {form.trigger_type === "env_threshold" && (
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="label">Measurement</label>
            <select className="input w-full" value={form.metric ?? ""} onChange={(e) => {
              set("metric", e.target.value || null);
              set("unit", e.target.value === "temperature" ? (form.unit ?? "°C") : null);
            }}>
              <option value="">Choose…</option>
              {Object.entries(ENV_METRICS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </div>
          {form.metric === "temperature" && (
            <div>
              <label className="label">Unit of the threshold</label>
              <select className="input w-full" value={form.unit ?? "°C"} onChange={(e) => set("unit", e.target.value)}>
                <option>°C</option><option>°F</option>
              </select>
            </div>
          )}
          <div>
            <label className="label">Room (optional)</label>
            <input className="input w-full" value={form.zone ?? ""} onChange={(e) => set("zone", e.target.value || null)} placeholder="any room" />
          </div>
          <ThresholdFields form={form} set={set} />
        </div>
      )}
      {form.trigger_type === "vital_threshold" && (
        <div className="grid grid-cols-3 gap-3">
          <div className="col-span-3">
            <label className="label">Vital sign</label>
            <select className="input w-full" value={form.metric ?? ""} onChange={(e) => set("metric", e.target.value || null)}>
              <option value="">Choose…</option>
              {Object.entries(VITAL_METRICS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <p className="mt-1 text-xs text-muted-foreground">
              Skips stale readings and an off-wrist watch; a high reading is ignored while the person is moving.
            </p>
          </div>
          <ThresholdFields form={form} set={set} />
        </div>
      )}

      {/* Care modes */}
      <div>
        <p className="label">Active when</p>
        <div className="flex gap-4">
          {([["alone", "Home alone"], ["with_others", "With others"]] as [CareModeKey, string][]).map(([m, label]) => {
            const modes = form.modes ?? form.effective_modes ?? ["alone", "with_others"];
            return (
              <label key={m} className="flex items-center gap-2 text-sm cursor-pointer select-none">
                <input type="checkbox" className="rounded" checked={modes.includes(m)}
                       onChange={(e) => set("modes", e.target.checked
                         ? [...new Set([...modes, m])] : modes.filter((x) => x !== m))} />
                {label}
              </label>
            );
          })}
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          With others at home the sensors can't tell who is moving, so rules that read movement as the patient's are normally off.
        </p>
      </div>

      {/* Time window */}
      <div>
        <label className="flex items-center gap-2 text-sm font-medium cursor-pointer select-none">
          <input
            type="checkbox"
            checked={useTW}
            onChange={(e) => set("time_window", e.target.checked ? { start: "20:00", end: "08:00" } : null)}
            className="rounded"
          />
          Restrict to time window
        </label>
        {useTW && (
          <div className="mt-2 grid grid-cols-2 gap-3">
            <div>
              <label className="label">Start (HH:MM)</label>
              <input className="input w-full" value={form.time_window?.start ?? "20:00"} onChange={(e) => set("time_window", { ...form.time_window, start: e.target.value })} />
            </div>
            <div>
              <label className="label">End (HH:MM)</label>
              <input className="input w-full" value={form.time_window?.end ?? "08:00"} onChange={(e) => set("time_window", { ...form.time_window, end: e.target.value })} />
            </div>
          </div>
        )}
      </div>

      {/* Message */}
      <div>
        <label className="label">
          Alert message
          <span className="ml-2 font-normal text-muted-foreground">
            variables: {"{{patient_name}} {{zone}} {{time}} {{duration}} {{value}} {{sensor}}"}
          </span>
        </label>
        <textarea
          className="input w-full"
          rows={2}
          value={form.message}
          onChange={(e) => set("message", e.target.value)}
          placeholder="e.g. {{patient_name}} has been in bathroom for {{duration}} min"
        />
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 pt-1">
        <button
          onClick={() => onSave(form)}
          disabled={!form.name || !form.message}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          <Save className="size-3.5" /> Save rule
        </button>
        <button
          onClick={onCancel}
          className="flex items-center gap-1.5 rounded-lg border px-4 py-2 text-sm font-medium hover:bg-muted"
        >
          <X className="size-3.5" /> Cancel
        </button>
      </div>
    </div>
  );
}

interface Props {
  profileId: string;
}

export function RulesAdmin({ profileId }: Props) {
  const [rules, setRules] = useState<Rule[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Rule | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  async function load() {
    setLoading(true);
    try {
      setRules(await api.rules(profileId));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [profileId]);

  async function handleToggle(ruleId: string) {
    try {
      const updated = await api.toggleRule(profileId, ruleId);
      setRules((rs) => rs.map((r) => (r.id === updated.id ? updated : r)));
    } catch (e) { setError(String(e)); }
  }

  async function handleDelete(ruleId: string) {
    if (!confirm("Delete this rule?")) return;
    try {
      await api.deleteRule(profileId, ruleId);
      setRules((rs) => rs.filter((r) => r.id !== ruleId));
    } catch (e) { setError(String(e)); }
  }

  async function handleSave(form: Omit<Rule, "id">) {
    try {
      if (editing === "new") {
        const created = await api.createRule(profileId, form);
        setRules((rs) => [...rs, created]);
      } else if (editing) {
        const updated = await api.updateRule(profileId, editing.id, form);
        setRules((rs) => rs.map((r) => (r.id === updated.id ? updated : r)));
      }
      setEditing(null);
    } catch (e) { setError(String(e)); }
  }

  function toggleExpand(id: string) {
    setExpanded((s) => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  }

  if (loading) return <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">Loading rules…</div>;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Alert Rules</h2>
          <p className="text-sm text-muted-foreground">
            {rules.filter((r) => r.enabled).length} active / {rules.length} total
          </p>
        </div>
        <button
          onClick={() => setEditing("new")}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          <Plus className="size-4" /> Add rule
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-400">
          {error}
        </div>
      )}

      {/* New rule editor */}
      {editing === "new" && (
        <RuleEditor
          initial={EMPTY_RULE}
          onSave={handleSave}
          onCancel={() => setEditing(null)}
        />
      )}

      {/* Rule list */}
      <div className="space-y-2">
        {rules.map((rule) => {
          const Icon = CATEGORY_ICON[rule.category] ?? ShieldAlert;
          const isExpanded = expanded.has(rule.id);
          return (
            <div key={rule.id} className={`rounded-2xl border bg-card transition-opacity ${rule.enabled ? "" : "opacity-60"}`}>
              {/* Main row */}
              <div className="flex items-center gap-3 px-4 py-3">
                <span className={`flex size-8 items-center justify-center rounded-lg bg-muted`}>
                  <Icon className="size-4 text-muted-foreground" />
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold leading-tight truncate">{rule.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {TRIGGER_LABELS[rule.trigger_type] ?? rule.trigger_type}
                    {conditionText(rule) && ` · ${conditionText(rule)}`}
                    {rule.zone && ` · ${rule.zone}`}
                    {!!rule.duration_minutes && ` · ${rule.duration_minutes}min`}
                    {rule.effective_modes?.length === 1 && ` · ${rule.effective_modes[0] === "alone" ? "home alone only" : "with others only"}`}
                  </p>
                </div>
                <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${SEVERITY_COLORS[rule.severity]}`}>
                  {rule.severity}
                </span>

                {/* Controls */}
                <button onClick={() => handleToggle(rule.id)} className="text-muted-foreground hover:text-foreground transition-colors">
                  {rule.enabled
                    ? <ToggleRight className="size-5 text-emerald-500" />
                    : <ToggleLeft className="size-5" />}
                </button>
                <button onClick={() => setEditing(rule)} className="text-muted-foreground hover:text-foreground transition-colors">
                  <Pencil className="size-4" />
                </button>
                <button onClick={() => handleDelete(rule.id)} className="text-muted-foreground hover:text-red-500 transition-colors">
                  <Trash2 className="size-4" />
                </button>
                <button onClick={() => toggleExpand(rule.id)} className="text-muted-foreground hover:text-foreground transition-colors">
                  {isExpanded ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
                </button>
              </div>

              {/* Expanded detail */}
              {isExpanded && (
                <div className="border-t px-4 py-3 text-xs text-muted-foreground space-y-1">
                  <p><span className="font-medium text-foreground">Message:</span> {rule.message}</p>
                  {rule.entity_id && <p><span className="font-medium text-foreground">Entity:</span> {rule.entity_id}</p>}
                  {rule.time_window && (
                    <p><span className="font-medium text-foreground">Time window:</span> {rule.time_window.start} – {rule.time_window.end}</p>
                  )}
                  <p><span className="font-medium text-foreground">Cooldown:</span> {rule.cooldown_minutes} min · <span className="font-medium text-foreground">ID:</span> {rule.id}</p>
                </div>
              )}

              {/* Inline editor */}
              {editing && editing !== "new" && editing.id === rule.id && (
                <div className="border-t p-4">
                  <RuleEditor
                    initial={editing}
                    onSave={handleSave}
                    onCancel={() => setEditing(null)}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {rules.length === 0 && !loading && (
        <div className="rounded-2xl border bg-muted/30 py-12 text-center text-sm text-muted-foreground">
          No rules yet. Add one above.
        </div>
      )}
    </div>
  );
}
