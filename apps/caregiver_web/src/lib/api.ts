// Typed REST client — the ONLY way the app talks to the backend.
// Every screen reads from here; no component fetches directly. Porting the app to Android
// means re-implementing just this file (same endpoints, same types).
//
// If a request fails (API down / HA unreachable), we fall back to bundled demo data so the
// UI still renders, and flip `usingMock` so the shell can show a "demo data" badge.
import type {
  ActivityEvent, Alert, CurrentStatus, ActivitySummary, ActivityPatterns, Profile, EnvReading,
  HealthData, HAEntity, Rule, CareMode, CareModeKey,
} from "./types";
import { mockStatus, mockActivities, mockAlerts, mockSummary, mockPatterns, mockEnvironment, mockHealth } from "./mock";

// Demo-mode care mode (no API): mutable so switching still works in the UI.
const DEMO_PAUSED = ["Living room inactivity (breakfast window)", "Long bathroom stay",
  "Night wandering", "Global inactivity (daytime)"];
let mockCareMode: CareMode = { mode: "alone", until: null, changed_at: null, paused_rules: [], active_rules: 17 };
const mockWithOthers: CareMode = { mode: "with_others", until: null, changed_at: null,
  paused_rules: DEMO_PAUSED, active_rules: 13 };

// Where the API lives.
//
// On the web this is "" and Vite's dev proxy forwards /api → :8000. In the packaged
// Android app there is no proxy and no localhost to speak of — 127.0.0.1 is the phone
// itself — so the URL has to be a real address the device can reach (LAN or VPN),
// and it has to be changeable WITHOUT rebuilding the APK. Resolution order:
//   1. whatever the user saved in the app (localStorage)
//   2. VITE_API_BASE baked in at build time
//   3. "" → same-origin / Vite proxy
const API_BASE_KEY = "dari.apiBase";

function readStoredBase(): string | null {
  try {
    return localStorage.getItem(API_BASE_KEY);
  } catch {
    return null; // private mode / storage disabled
  }
}

let BASE = readStoredBase() ?? import.meta.env.VITE_API_BASE ?? "";

export function getApiBase(): string {
  return BASE;
}

/** Persist a new API base URL. Pass "" to fall back to the build-time default. */
export function setApiBase(url: string): void {
  const clean = url.trim().replace(/\/+$/, ""); // strip trailing slashes
  BASE = clean || (import.meta.env.VITE_API_BASE ?? "");
  try {
    if (clean) localStorage.setItem(API_BASE_KEY, clean);
    else localStorage.removeItem(API_BASE_KEY);
  } catch {
    /* storage unavailable — the in-memory value still applies for this session */
  }
}

/** Probe a candidate API base so the settings UI can report success before saving. */
export async function probeApiBase(url: string): Promise<boolean> {
  const base = url.trim().replace(/\/+$/, "");
  try {
    const res = await fetch(`${base}/api/profiles`, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(6000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

let _usingMock = false;
const listeners = new Set<(v: boolean) => void>();
function setMock(v: boolean) {
  if (v !== _usingMock) {
    _usingMock = v;
    listeners.forEach((l) => l(v));
  }
}
export function usingMock() {
  return _usingMock;
}
export function onMockChange(cb: (v: boolean) => void) {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

async function get<T>(path: string, fallback: T): Promise<T> {
  try {
    const res = await fetch(`${BASE}${path}`, { headers: { Accept: "application/json" } });
    if (!res.ok) throw new Error(`${res.status}`);
    setMock(false);
    return (await res.json()) as T;
  } catch {
    setMock(true);
    return fallback;
  }
}

export const api = {
  currentStatus: (profileId: string) =>
    get<CurrentStatus>(`/api/current_status?profile_id=${profileId}`, mockStatus),

  activityLog: (profileId: string, opts: { category?: string; since?: string; limit?: number } = {}) => {
    const q = new URLSearchParams({ profile_id: profileId });
    if (opts.category) q.set("category", opts.category);
    if (opts.since) q.set("since", opts.since);
    if (opts.limit) q.set("limit", String(opts.limit));
    return get<ActivityEvent[]>(`/api/activity_log?${q}`, mockActivities);
  },

  activitySummary: (profileId: string, days = 7) =>
    get<ActivitySummary>(`/api/activity_summary?profile_id=${profileId}&days=${days}`, mockSummary),

  activityPatterns: (profileId: string, days = 14) =>
    get<ActivityPatterns>(`/api/activity_patterns?profile_id=${profileId}&days=${days}`, mockPatterns),

  alerts: (profileId: string, opts: { acknowledged?: boolean; limit?: number } = {}) => {
    const q = new URLSearchParams({ profile_id: profileId });
    if (opts.acknowledged !== undefined) q.set("acknowledged", String(opts.acknowledged));
    if (opts.limit) q.set("limit", String(opts.limit));
    return get<Alert[]>(`/api/alerts?${q}`, mockAlerts);
  },

  environment: (profileId: string) =>
    get<EnvReading[]>(`/api/environment?profile_id=${profileId}`, mockEnvironment),

  health: (profileId: string) =>
    get<HealthData>(`/api/health?profile_id=${profileId}`, mockHealth),

  profiles: () => get<Profile[]>(`/api/profiles`, [
    { profile_id: "patient-001", patient_name: "Patient A", caregiver_name: "Caregiver A" },
  ]),

  careMode: (profileId: string) =>
    get<CareMode>(`/api/care_mode?profile_id=${profileId}`, mockCareMode),

  /** What switching to `mode` would pause, without switching. */
  previewCareMode: (profileId: string, mode: CareModeKey) =>
    get<CareMode>(`/api/care_mode/preview?profile_id=${profileId}&mode=${mode}`,
      mode === "alone" ? { ...mockCareMode, mode, paused_rules: [] } : mockWithOthers),

  setCareMode: async (profileId: string, mode: CareModeKey, durationMinutes: number | null) => {
    let res: Response;
    try {
      res = await fetch(`${BASE}/api/care_mode?profile_id=${profileId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, duration_minutes: durationMinutes }),
      });
    } catch {
      // API unreachable (demo mode): keep the choice locally so the UI still behaves.
      mockCareMode = mode === "alone"
        ? { ...mockCareMode, mode, until: null, paused_rules: [] }
        : { ...mockWithOthers, until: durationMinutes
            ? new Date(Date.now() + durationMinutes * 60_000).toISOString() : null };
      return mockCareMode;
    }
    if (!res.ok) throw new Error(`${res.status}`);
    return res.json() as Promise<CareMode>;
  },

  acknowledgeAlert: async (alertId: string) => {
    try {
      await fetch(`${BASE}/api/alerts/${alertId}/acknowledge`, { method: "POST" });
    } catch {
      /* ignore in demo mode */
    }
  },

  // ── Admin endpoints ────────────────────────────────────────────────────────

  haEntities: (domain?: string) => {
    const q = domain ? `?domain=${domain}` : "";
    return get<HAEntity[]>(`/api/ha_entities${q}`, []);
  },

  watchConfig: (profileId: string) =>
    get<Record<string, string>>(`/api/watch_config?profile_id=${profileId}`, {}),

  putWatchConfig: async (profileId: string, config: Record<string, string>) => {
    const res = await fetch(`${BASE}/api/watch_config?profile_id=${profileId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    });
    if (!res.ok) throw new Error(`${res.status}`);
    return res.json() as Promise<Record<string, string>>;
  },

  rules: (profileId: string) =>
    get<Rule[]>(`/api/rules?profile_id=${profileId}`, []),

  createRule: async (profileId: string, rule: Omit<Rule, "id">) => {
    const res = await fetch(`${BASE}/api/rules?profile_id=${profileId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(rule),
    });
    if (!res.ok) throw new Error(`${res.status}`);
    return res.json() as Promise<Rule>;
  },

  updateRule: async (profileId: string, ruleId: string, rule: Omit<Rule, "id">) => {
    const res = await fetch(`${BASE}/api/rules/${ruleId}?profile_id=${profileId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(rule),
    });
    if (!res.ok) throw new Error(`${res.status}`);
    return res.json() as Promise<Rule>;
  },

  toggleRule: async (profileId: string, ruleId: string) => {
    const res = await fetch(`${BASE}/api/rules/${ruleId}/toggle?profile_id=${profileId}`, {
      method: "PATCH",
    });
    if (!res.ok) throw new Error(`${res.status}`);
    return res.json() as Promise<Rule>;
  },

  deleteRule: async (profileId: string, ruleId: string) => {
    const res = await fetch(`${BASE}/api/rules/${ruleId}?profile_id=${profileId}`, {
      method: "DELETE",
    });
    if (!res.ok) throw new Error(`${res.status}`);
  },

  haAreas: () =>
    get<{ areas: string[]; by_area: Record<string, Record<string, string[]>> }>(
      `/api/ha_areas`,
      { areas: [], by_area: {} },
    ),

  sensorHistory: (entityIds: string[], hours = 24) => {
    const q = new URLSearchParams({ entity_ids: entityIds.join(","), hours: String(hours) });
    return get<Record<string, { state: string; last_changed: string }[]>>(
      `/api/sensor_history?${q}`,
      {},
    );
  },

  cameras: () =>
    get<{ entity_id: string; friendly_name: string; area: string }[]>(`/api/cameras`, []),
};
