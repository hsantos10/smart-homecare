// ─────────────────────────────────────────────────────────────────────────────
// Shared API contract.
//
// These types mirror the FastAPI response models in `api/main.py` exactly. They are
// the single source of truth for the data shape and are intended to be PORTED VERBATIM
// to the Android app (e.g. as Kotlin data classes / a shared TS layer in React Native).
// Keep them in sync with the backend; nothing here is web-specific.
// ─────────────────────────────────────────────────────────────────────────────

export type Severity = "info" | "notice" | "warning";
export type RiskLevel = "ok" | "attention" | "alert";
export type ActivityCategory =
  | "sleep" | "hygiene" | "meal" | "mobility" | "rest"
  | "exit" | "safety" | "environment" | "unknown";

export interface ActivityEvent {
  id: string;
  profile_id: string;
  timestamp: string;        // ISO-8601 UTC
  activity: string;         // machine key, e.g. "woke_up"
  label: string;            // human-readable
  category: ActivityCategory;
  zone: string | null;
  detail: string | null;
  icon: string;             // lucide icon hint
  severity: Severity;
  confidence: number;       // 0..1
  source: string;           // "heuristic" | "ml" | "demo"
}

export interface CurrentStatus {
  profile_id: string;
  patient_name: string;
  timestamp: string;
  home: boolean;
  current_zone: string | null;
  current_activity: string;
  activity_label: string;
  activity_icon: string;
  activity_category: ActivityCategory;
  since: string | null;
  duration_minutes: number | null;
  last_movement: string | null;
  presence_by_zone: Record<string, boolean>;
  risk_level: RiskLevel;
  active_alerts: number;
}

export interface Alert {
  id: string;
  profile_id: string;
  rule_id: string;
  rule_name: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
  category: string;
  message: string;
  zone: string | null;
  timestamp: string;
  acknowledged: boolean;
}

export interface ActivitySummary {
  profile_id: string;
  days: number;
  total: number;
  by_category: Record<string, number>;
  by_activity: Record<string, number>;
  by_day: Record<string, Record<string, number>>;
  by_hour: Record<string, number>;
}

export interface ClockStat {
  mean: string; // "HH:MM" local
  spread_min: number;
  n: number;
}

export interface ActivityPatterns {
  profile_id: string;
  days: number;
  days_with_data: number;
  wake_time: ClockStat | null;
  bed_time: ClockStat | null;
  breakfast_time: ClockStat | null;
  midday_meal_time: ClockStat | null;
  night_bathroom_visits_per_night: number;
  outings_per_day: number;
  time_in_room_pct: Record<string, number>;
  routine_regularity: "high" | "moderate" | "low" | null;
}

export interface Profile {
  profile_id: string;
  patient_name: string;
  caregiver_name: string;
}

export interface EnvReading {
  entity_id: string;
  name: string;
  area: string | null;
  value: number | null;
  unit: string;
  kind: "temperature" | "humidity" | "co2" | "pm25" | "co" | "voc" | "other";
  /** From the profile's env_threshold rules; null when no rule covers this kind. */
  status?: "ok" | "warn" | "alert" | null;
  status_text?: string | null;
}

// ── Admin types ───────────────────────────────────────────────────────────────

export interface HAEntity {
  entity_id: string;
  friendly_name: string;
  state: string;
  unit: string;
  domain: string;
  last_changed: string | null;
}

export interface RuleTimeWindow {
  start: string;
  end: string;
}

export interface Rule {
  id: string;
  name: string;
  enabled: boolean;
  category: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
  trigger_type: string;
  message: string;
  zone: string | null;
  entity_id: string | null;
  duration_minutes: number | null;
  no_return_minutes: number | null;
  operator: string | null;
  value: number | null;
  metric?: string | null;
  unit?: string | null;
  time_window: RuleTimeWindow | null;
  cooldown_minutes: number;
  /** Care modes the rule runs in, as stored; null = the default for its trigger. */
  modes?: CareModeKey[] | null;
  /** What the rule engine actually uses (server-resolved default). */
  effective_modes?: CareModeKey[];
}

// ── Care mode ─────────────────────────────────────────────────────────────────

export type CareModeKey = "alone" | "with_others";

export interface CareMode {
  mode: CareModeKey;
  /** ISO time "with others" reverts to "alone"; null = until switched back. */
  until: string | null;
  changed_at: string | null;
  /** Names of enabled rules this mode pauses. */
  paused_rules: string[];
  active_rules: number;
}

export interface HealthData {
  watch_name: string;
  connected: boolean;
  heart_rate: number | null;
  heart_rate_unit: string;
  steps_today: number | null;
  calories: number | null;
  distance: number | null;
  distance_unit: string;
  battery_level: number | null;
  battery_state: string | null;   // "charging" | "discharging" | "full" | null
  on_body: boolean | null;
  activity_state: string | null;  // "active" | "passive" | "still" | null
  phone_activity: string | null;
  sleep_confidence: number | null;
  last_updated: string | null;
}
