import { useState, useMemo } from "react";
import { Search, Play, X } from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from "recharts";
import { api, getApiBase } from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import type { HAEntity } from "@/lib/types";

const COLORS = [
  "#6366f1", "#f59e0b", "#10b981", "#ef4444",
  "#8b5cf6", "#06b6d4", "#f97316", "#84cc16",
];

type Segment    = { id: string; start: number; end: number; isOn: boolean };
type QuickRange = "1h" | "6h" | "24h" | "7d" | "custom";

const QUICK: { value: QuickRange; label: string; hours: number }[] = [
  { value: "1h",  label: "1 hour",   hours: 1 },
  { value: "6h",  label: "6 hours",  hours: 6 },
  { value: "24h", label: "24 hours", hours: 24 },
  { value: "7d",  label: "7 days",   hours: 168 },
  { value: "custom", label: "Custom", hours: 0 },
];

const USEFUL_DOMAINS = new Set([
  "sensor", "binary_sensor", "person", "device_tracker", "input_boolean", "switch",
]);
const NOISY_DOMAINS = new Set([
  "camera", "automation", "scene", "script", "update", "button",
  "input_button", "image", "media_player", "tts", "stt", "todo",
  "calendar", "persistent_notification",
]);

function isNumeric(v: string) {
  return !isNaN(parseFloat(v)) && isFinite(Number(v));
}

const OFF_STATES = new Set(["off", "closed", "not_home", "false", "clear"]);
const SKIP_STATES = new Set(["unavailable", "unknown"]);

function fmtAxisTime(ts: string) {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch { return ts.slice(11, 16); }
}

// Recharts types `labelFormatter`'s first argument as ReactNode, so this has to accept
// more than a string even though every call site passes an ISO timestamp.
function fmtTooltipTime(ts: unknown) {
  const s = typeof ts === "string" ? ts : String(ts ?? "");
  try {
    return new Date(s).toLocaleString([], {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch { return s; }
}

export function SensorHistory() {
  const [areaFilter,    setAreaFilter]    = useState("All");
  const [domainFilter,  setDomainFilter]  = useState("All");
  const [query,         setQuery]         = useState("");
  const [selected,      setSelected]      = useState<HAEntity[]>([]);
  const [quickRange,    setQuickRange]    = useState<QuickRange>("24h");
  const [customStart,   setCustomStart]   = useState("");
  const [customEnd,     setCustomEnd]     = useState("");
  const [histData,      setHistData]      = useState<Record<string, { state: string; last_changed: string }[]> | null>(null);
  const [queryWindow,   setQueryWindow]   = useState<{ start: string; end: string } | null>(null);
  const [holdMinutes,   setHoldMinutes]   = useState(2);
  const [fetching,      setFetching]      = useState(false);
  const [error,         setError]         = useState<string | null>(null);

  const { data: entities = [] } = usePolling(() => api.haEntities(), 60_000, []);
  const { data: areasData }     = usePolling(() => api.haAreas(), 60_000, []);
  const areas   = areasData?.areas ?? [];
  const byArea  = areasData?.by_area ?? {};

  const allDomains = useMemo(() =>
    Array.from(new Set(entities.map((e) => e.domain))).sort(),
    [entities],
  );
  const usefulDomains = allDomains.filter((d) => !NOISY_DOMAINS.has(d));

  const areaEntitySet = useMemo(() => {
    if (areaFilter === "All") return null;
    const bucket = byArea[areaFilter] ?? {};
    return new Set(Object.values(bucket).flat() as string[]);
  }, [areaFilter, byArea]);

  const filtered = useMemo(() => {
    const q = query.toLowerCase();
    return entities.filter((e) => {
      if (!USEFUL_DOMAINS.has(e.domain)) return false;
      if (domainFilter !== "All" && e.domain !== domainFilter) return false;
      if (areaEntitySet && !areaEntitySet.has(e.entity_id)) return false;
      if (q && !e.entity_id.toLowerCase().includes(q) && !e.friendly_name.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [entities, domainFilter, areaEntitySet, query]);

  function toggle(e: HAEntity) {
    setSelected((prev) =>
      prev.some((s) => s.entity_id === e.entity_id)
        ? prev.filter((s) => s.entity_id !== e.entity_id)
        : prev.length < 8 ? [...prev, e] : prev,
    );
  }

  async function runQuery() {
    if (selected.length === 0) return;
    setFetching(true);
    setError(null);
    try {
      const q = QUICK.find((r) => r.value === quickRange)!;
      let data: Record<string, { state: string; last_changed: string }[]>;
      let windowStart: Date;
      let windowEnd: Date = new Date();
      if (quickRange === "custom" && customStart && customEnd) {
        windowStart = new Date(customStart);
        windowEnd = new Date(customEnd);
        const q2 = new URLSearchParams({
          entity_ids: selected.map((e) => e.entity_id).join(","),
          start: windowStart.toISOString(),
          end: windowEnd.toISOString(),
        });
        const res = await fetch(`${getApiBase()}/api/sensor_history?${q2}`);
        if (!res.ok) throw new Error(`${res.status}`);
        data = await res.json();
      } else {
        windowStart = new Date(windowEnd.getTime() - q.hours * 3600 * 1000);
        data = await api.sensorHistory(selected.map((e) => e.entity_id), q.hours);
      }
      setQueryWindow({ start: windowStart.toISOString(), end: windowEnd.toISOString() });
      setHistData(data);
    } catch (err) {
      setError(String(err));
    } finally {
      setFetching(false);
    }
  }

  // Separate numeric from binary/state entities
  const numericIds = histData
    ? Object.entries(histData)
        .filter(([, recs]) => recs.some((r) => isNumeric(r.state)))
        .map(([id]) => id)
    : [];
  const binaryIds = histData
    ? Object.keys(histData).filter((id) => !numericIds.includes(id))
    : [];

  function buildNumericData() {
    if (!histData) return [];
    const allTimes = new Set<string>();
    for (const id of numericIds) {
      for (const rec of histData[id]) allTimes.add(rec.last_changed);
    }
    const sorted = Array.from(allTimes).sort();
    return sorted.map((t) => {
      const row: Record<string, string | number> = { time: t };
      for (const id of numericIds) {
        const recs = histData[id];
        const match = recs.filter((r) => r.last_changed <= t).at(-1);
        if (match && isNumeric(match.state)) row[id] = parseFloat(match.state);
      }
      return row;
    });
  }

  function applyHold(
    recs: { state: string; last_changed: string }[],
    holdMs: number,
  ): { state: string; last_changed: string }[] {
    // Strip unavailable/unknown entirely — treat as transparent (no state change).
    const cleaned = recs.filter(r => !SKIP_STATES.has(r.state.toLowerCase()));

    const out: { state: string; last_changed: string }[] = [];
    for (let i = 0; i < cleaned.length; i++) {
      const curr = cleaned[i];
      const isOff = OFF_STATES.has(curr.state.toLowerCase());
      if (!isOff) { out.push(curr); continue; }

      // Look ahead for next non-off event
      const currTime = new Date(curr.last_changed).getTime();
      let nextOnIdx = -1;
      for (let j = i + 1; j < cleaned.length; j++) {
        if (!OFF_STATES.has(cleaned[j].state.toLowerCase())) { nextOnIdx = j; break; }
      }
      if (nextOnIdx !== -1) {
        const nextOnTime = new Date(cleaned[nextOnIdx].last_changed).getTime();
        if (nextOnTime - currTime <= holdMs) continue; // suppress brief off
      }
      out.push(curr);
    }
    return out;
  }

  function buildBinarySegments(): Record<string, Segment[]> {
    if (!histData || !queryWindow) return {};
    const holdMs   = holdMinutes * 60 * 1000;
    const winStart = new Date(queryWindow.start).getTime();
    const winEnd   = new Date(queryWindow.end).getTime();
    const out: Record<string, Segment[]> = {};
    for (const id of binaryIds) {
      const held     = applyHold(histData[id], holdMs);
      const firstRaw = histData[id].find(r => !SKIP_STATES.has(r.state.toLowerCase()));
      let recs       = held;
      if (firstRaw && (held.length === 0 || held[0].last_changed > queryWindow.start)) {
        recs = [{ state: firstRaw.state, last_changed: queryWindow.start }, ...held];
      }
      const segs: Segment[] = [];
      for (let i = 0; i < recs.length; i++) {
        const start = Math.max(new Date(recs[i].last_changed).getTime(), winStart);
        const end   = i + 1 < recs.length ? new Date(recs[i + 1].last_changed).getTime() : winEnd;
        segs.push({ id, start, end, isOn: !OFF_STATES.has(recs[i].state.toLowerCase()) });
      }
      out[id] = segs;
    }
    return out;
  }

  const numData  = buildNumericData();
  const binSegs  = buildBinarySegments();

  function label(id: string) {
    return entities.find((e) => e.entity_id === id)?.friendly_name || id;
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Sensor History</h2>
        <p className="text-sm text-muted-foreground">Query historical state from Home Assistant</p>
      </div>

      <div className="grid grid-cols-[1fr_auto] gap-4">
        {/* Left: entity picker */}
        <div className="rounded-xl border bg-background overflow-hidden">
          {/* Filter row */}
          <div className="flex flex-wrap gap-2 p-3 border-b bg-muted/30">
            <select
              value={areaFilter}
              onChange={(e) => setAreaFilter(e.target.value)}
              className="rounded-lg border bg-background px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
            >
              <option>All</option>
              {areas.map((a) => <option key={a}>{a}</option>)}
            </select>
            <select
              value={domainFilter}
              onChange={(e) => setDomainFilter(e.target.value)}
              className="rounded-lg border bg-background px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
            >
              <option>All</option>
              {usefulDomains.map((d) => <option key={d}>{d}</option>)}
            </select>
            <div className="relative flex-1 min-w-32">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
              <input
                type="text"
                placeholder="Search..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="w-full rounded-lg border bg-background pl-8 pr-3 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
              />
            </div>
          </div>

          {/* Entity list */}
          <div className="overflow-auto max-h-64">
            {filtered.length === 0 ? (
              <p className="p-4 text-sm text-muted-foreground">No entities match.</p>
            ) : (
              <table className="w-full text-sm">
                <tbody>
                  {filtered.map((e) => {
                    const isSel = selected.some((s) => s.entity_id === e.entity_id);
                    return (
                      <tr
                        key={e.entity_id}
                        onClick={() => toggle(e)}
                        className={`border-t cursor-pointer transition-colors ${
                          isSel ? "bg-primary/10" : "hover:bg-muted/50"
                        }`}
                      >
                        <td className="w-8 pl-3 py-2">
                          <input type="checkbox" checked={isSel} readOnly className="pointer-events-none" />
                        </td>
                        <td className="px-2 py-2 font-medium">{e.friendly_name || e.entity_id}</td>
                        <td className="px-2 py-2 font-mono text-xs text-muted-foreground">{e.state}{e.unit ? ` ${e.unit}` : ""}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* Right: time range + run */}
        <div className="flex flex-col gap-3 min-w-48">
          <div className="rounded-xl border bg-background p-3 space-y-2">
            <p className="text-xs font-medium text-muted-foreground">Hold timer (binary)</p>
            <div className="flex items-center gap-2">
              <input
                type="range"
                min={0}
                max={10}
                step={1}
                value={holdMinutes}
                onChange={(e) => setHoldMinutes(Number(e.target.value))}
                className="flex-1"
              />
              <span className="text-xs w-12 text-right">{holdMinutes === 0 ? "off" : `${holdMinutes} min`}</span>
            </div>
            <p className="text-xs text-muted-foreground">Suppress brief off-states shorter than this</p>
          </div>

          <div className="rounded-xl border bg-background p-3 space-y-2">
            <p className="text-xs font-medium text-muted-foreground">Time range</p>
            {QUICK.map((r) => (
              <label key={r.value} className="flex items-center gap-2 cursor-pointer text-sm">
                <input
                  type="radio"
                  name="quickRange"
                  value={r.value}
                  checked={quickRange === r.value}
                  onChange={() => setQuickRange(r.value)}
                />
                {r.label}
              </label>
            ))}
            {quickRange === "custom" && (
              <div className="space-y-1.5 pt-1">
                <input
                  type="datetime-local"
                  value={customStart}
                  onChange={(e) => setCustomStart(e.target.value)}
                  className="w-full rounded border bg-background px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-primary/30"
                />
                <input
                  type="datetime-local"
                  value={customEnd}
                  onChange={(e) => setCustomEnd(e.target.value)}
                  className="w-full rounded border bg-background px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-primary/30"
                />
              </div>
            )}
          </div>

          <button
            onClick={runQuery}
            disabled={selected.length === 0 || fetching}
            className="flex items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
          >
            <Play className="size-4" />
            {fetching ? "Fetching..." : `Query (${selected.length})`}
          </button>

          {/* Selected chips */}
          {selected.length > 0 && (
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">Selected</p>
              {selected.map((e, i) => (
                <div
                  key={e.entity_id}
                  className="flex items-center gap-1.5 rounded-lg border px-2 py-1 text-xs"
                  style={{ borderLeftColor: COLORS[i % COLORS.length], borderLeftWidth: 3 }}
                >
                  <span className="flex-1 truncate">{e.friendly_name || e.entity_id}</span>
                  <button onClick={() => toggle(e)} className="text-muted-foreground hover:text-foreground">
                    <X className="size-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Charts */}
      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 dark:bg-red-950/20 p-4 text-sm text-red-700 dark:text-red-400">
          {error}
        </div>
      )}

      {histData && !error && (
        <div className="space-y-4">
          {numericIds.length > 0 && numData.length > 0 && (
            <div className="rounded-xl border bg-background p-4">
              <p className="text-sm font-medium mb-3">Numeric sensors</p>
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={numData} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="time" tickFormatter={fmtAxisTime} tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip
                    labelFormatter={fmtTooltipTime}
                    contentStyle={{ fontSize: 12 }}
                    formatter={(v, name) => [v, label(String(name))]}
                  />
                  <Legend formatter={(v) => label(v)} wrapperStyle={{ fontSize: 12 }} />
                  {numericIds.map((id, i) => (
                    <Line
                      key={id}
                      type="monotone"
                      dataKey={id}
                      stroke={COLORS[i % COLORS.length]}
                      dot={false}
                      strokeWidth={2}
                      connectNulls
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {binaryIds.length > 0 && queryWindow && Object.keys(binSegs).length > 0 && (() => {
            const winStart  = new Date(queryWindow.start).getTime();
            const winEnd    = new Date(queryWindow.end).getTime();
            const winDur    = winEnd - winStart;
            const tickMs    = winDur > 48 * 3_600_000 ? 12 * 3_600_000
                            : winDur >  6 * 3_600_000 ?  2 * 3_600_000
                            : winDur >  2 * 3_600_000 ? 30 * 60_000
                            :                           15 * 60_000;
            const firstTick = Math.ceil(winStart / tickMs) * tickMs;
            const ticks: number[] = [];
            for (let t = firstTick; t <= winEnd; t += tickMs) ticks.push(t);
            const pct = (ms: number) => `${((ms - winStart) / winDur) * 100}%`;

            return (
              <div className="rounded-xl border bg-background p-4">
                <p className="text-sm font-medium mb-3">Binary / state sensors</p>
                <div className="flex text-xs">
                  {/* Label column */}
                  <div className="shrink-0 w-40 pr-2">
                    {binaryIds.map((id, i) => (
                      <div
                        key={id}
                        className="flex items-center h-8 font-medium truncate"
                        style={{ color: COLORS[(numericIds.length + i) % COLORS.length] }}
                      >
                        <span className="truncate">{label(id)}</span>
                      </div>
                    ))}
                    <div className="h-7" />
                  </div>

                  {/* Timeline column */}
                  <div className="relative flex-1 min-w-0">
                    <div className="flex flex-col gap-1">
                      {binaryIds.map((id, i) => {
                        const color = COLORS[(numericIds.length + i) % COLORS.length];
                        const segs  = binSegs[id] ?? [];
                        return (
                          <div key={id} className="relative h-7 rounded-sm bg-muted/40 overflow-hidden">
                            {/* vertical grid lines */}
                            {ticks.map(t => (
                              <div key={t} className="absolute inset-y-0 w-px bg-border/50" style={{ left: pct(t) }} />
                            ))}
                            {/* on-segments */}
                            {segs.filter(s => s.isOn).map((seg, j) => {
                              const dur    = seg.end - seg.start;
                              const durStr = dur < 60_000     ? `${Math.round(dur / 1_000)}s`
                                           : dur < 3_600_000  ? `${Math.round(dur / 60_000)}m`
                                           : `${(dur / 3_600_000).toFixed(1)}h`;
                              return (
                                <div
                                  key={j}
                                  className="absolute inset-y-0"
                                  style={{
                                    left:  pct(seg.start),
                                    width: `${Math.max((seg.end - seg.start) / winDur * 100, 0.15)}%`,
                                    backgroundColor: color,
                                    opacity: 0.85,
                                  }}
                                  title={`${label(id)}: detected — ${new Date(seg.start).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} (${durStr})`}
                                />
                              );
                            })}
                          </div>
                        );
                      })}
                    </div>

                    {/* Time axis */}
                    <div className="relative h-7 mt-1">
                      {ticks.map(t => (
                        <div
                          key={t}
                          className="absolute flex flex-col items-center"
                          style={{ left: pct(t), transform: "translateX(-50%)" }}
                        >
                          <div className="w-px h-1.5 bg-border" />
                          <span className="text-muted-foreground mt-0.5 whitespace-nowrap">
                            {new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Legend */}
                <div className="flex flex-wrap gap-3 mt-2 pl-40">
                  {binaryIds.map((id, i) => (
                    <div key={id} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <div className="w-3 h-2.5 rounded-sm" style={{ backgroundColor: COLORS[(numericIds.length + i) % COLORS.length], opacity: 0.85 }} />
                      {label(id)}
                    </div>
                  ))}
                </div>
              </div>
            );
          })()}

          {/* Raw table */}
          <details className="rounded-xl border bg-background">
            <summary className="cursor-pointer px-4 py-3 text-sm font-medium select-none">
              Raw data table
            </summary>
            <div className="overflow-auto max-h-64 border-t">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-muted/80">
                  <tr>
                    <th className="text-left px-3 py-2 font-medium text-muted-foreground">Sensor</th>
                    <th className="text-left px-3 py-2 font-medium text-muted-foreground">Time</th>
                    <th className="text-left px-3 py-2 font-medium text-muted-foreground">State</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(histData).flatMap(([id, recs]) =>
                    recs.map((r, i) => (
                      <tr key={`${id}-${i}`} className="border-t hover:bg-muted/30">
                        <td className="px-3 py-1.5">{label(id)}</td>
                        <td className="px-3 py-1.5 text-muted-foreground font-mono">{fmtTooltipTime(r.last_changed)}</td>
                        <td className="px-3 py-1.5 font-mono">{r.state}</td>
                      </tr>
                    ))
                  ).sort((a, b) => {
                    const ta = (a as any).key?.split("-").slice(1).join("-") ?? "";
                    const tb = (b as any).key?.split("-").slice(1).join("-") ?? "";
                    return ta.localeCompare(tb);
                  })}
                </tbody>
              </table>
            </div>
          </details>
        </div>
      )}

      {histData && Object.keys(histData).length === 0 && !error && (
        <div className="rounded-xl border bg-muted/30 p-8 text-center text-sm text-muted-foreground">
          No data returned — the sensors may have no state changes in this window.
        </div>
      )}
    </div>
  );
}
