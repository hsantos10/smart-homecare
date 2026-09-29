// Fallback demo data — used only when the API is unreachable, so the UI always renders
// (useful for offline UI work and for the Android team to preview expected shapes).
import type { ActivityEvent, Alert, CurrentStatus, ActivitySummary, ActivityPatterns, EnvReading, HealthData } from "./types";

const now = Date.now();
const ago = (min: number) => new Date(now - min * 60_000).toISOString();

export const mockStatus: CurrentStatus = {
  profile_id: "patient-001",
  patient_name: "Patient A",
  timestamp: new Date(now).toISOString(),
  home: true,
  current_zone: "Living room",
  current_activity: "sitting",
  activity_label: "Sitting",
  activity_icon: "armchair",
  activity_category: "rest",
  since: ago(26),
  duration_minutes: 26,
  last_movement: ago(2),
  presence_by_zone: { "Living room": true, Bedroom: false, "Bedroom Bathroom": false },
  risk_level: "ok",
  active_alerts: 0,
};

export const mockActivities: ActivityEvent[] = [
  { id: "1", profile_id: "patient-001", timestamp: ago(2), activity: "sitting", label: "Sitting", category: "rest", zone: "Living room", detail: null, icon: "armchair", severity: "info", confidence: 0.8, source: "demo" },
  { id: "2", profile_id: "patient-001", timestamp: ago(28), activity: "front_door_opened", label: "Front door opened", category: "exit", zone: "Front Door", detail: "Unusual time", icon: "door-open", severity: "notice", confidence: 1, source: "demo" },
  { id: "3", profile_id: "patient-001", timestamp: ago(33), activity: "in_living_room", label: "In the living room", category: "mobility", zone: "Living room", detail: null, icon: "sofa", severity: "info", confidence: 0.85, source: "demo" },
  { id: "4", profile_id: "patient-001", timestamp: ago(45), activity: "breakfast", label: "Breakfast", category: "meal", zone: "Kitchen", detail: null, icon: "coffee", severity: "info", confidence: 0.7, source: "demo" },
  { id: "5", profile_id: "patient-001", timestamp: ago(70), activity: "in_bathroom", label: "In the bathroom", category: "hygiene", zone: "Bedroom Bathroom", detail: null, icon: "bath", severity: "info", confidence: 0.85, source: "demo" },
  { id: "6", profile_id: "patient-001", timestamp: ago(86), activity: "woke_up", label: "Woke up", category: "sleep", zone: "Bedroom", detail: null, icon: "sun", severity: "info", confidence: 1, source: "demo" },
  { id: "7", profile_id: "patient-001", timestamp: ago(410), activity: "went_to_bed", label: "Went to bed", category: "sleep", zone: "Bedroom", detail: null, icon: "bed", severity: "info", confidence: 1, source: "demo" },
];

export const mockAlerts: Alert[] = [
  { id: "a1", profile_id: "patient-001", rule_id: "rule-002", rule_name: "Night exit — front door", severity: "HIGH", category: "Safety", message: "Front door opened at 9:32 AM — Patient A may have left", zone: "Front Door", timestamp: ago(28), acknowledged: false },
];

export const mockEnvironment: EnvReading[] = [
  { entity_id: "sensor.living_temp", name: "Living Room Temperature", area: "Living room", value: 22.8, unit: "°C", kind: "temperature" },
  { entity_id: "sensor.living_humidity", name: "Living Room Humidity", area: "Living room", value: 44, unit: "%", kind: "humidity" },
  { entity_id: "sensor.bedroom_temp", name: "Bedroom Temperature", area: "Bedroom", value: 21.5, unit: "°C", kind: "temperature" },
  { entity_id: "sensor.bedroom_humidity", name: "Bedroom Humidity", area: "Bedroom", value: 46, unit: "%", kind: "humidity" },
];

export const mockHealth: HealthData = {
  watch_name: "Smartwatch",
  connected: true,
  heart_rate: 72,
  heart_rate_unit: "bpm",
  steps_today: 2847,
  calories: 1450.0,
  distance: 5280.0,
  distance_unit: "ft",
  battery_level: 78,
  battery_state: "discharging",
  on_body: true,
  activity_state: "passive",
  phone_activity: "still",
  sleep_confidence: 12.0,
  last_updated: new Date(Date.now() - 3 * 60_000).toISOString(),
};

export const mockSummary: ActivitySummary = {
  profile_id: "patient-001",
  days: 7,
  total: 142,
  by_category: { sleep: 14, hygiene: 21, meal: 18, mobility: 47, rest: 28, exit: 9, safety: 5 },
  by_activity: {},
  by_day: {},
  by_hour: { "0": 1, "1": 0, "2": 0, "3": 1, "4": 0, "5": 2, "6": 5, "7": 9, "8": 11, "9": 8, "10": 6, "11": 7, "12": 9, "13": 6, "14": 5, "15": 7, "16": 8, "17": 10, "18": 9, "19": 7, "20": 5, "21": 3, "22": 2, "23": 1 },
};

export const mockPatterns: ActivityPatterns = {
  profile_id: "patient-001",
  days: 14,
  days_with_data: 12,
  wake_time: { mean: "07:12", spread_min: 24, n: 12 },
  bed_time: { mean: "22:34", spread_min: 38, n: 11 },
  breakfast_time: { mean: "08:05", spread_min: 31, n: 10 },
  midday_meal_time: { mean: "12:40", spread_min: 45, n: 9 },
  night_bathroom_visits_per_night: 1.3,
  outings_per_day: 0.8,
  time_in_room_pct: { "Living room": 52, Bedroom: 24, "Bedroom Bathroom": 14, "Study room": 10 },
  routine_regularity: "high",
};
