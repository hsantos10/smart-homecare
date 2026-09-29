import { useState, useMemo } from "react";
import { RefreshCw, Search } from "lucide-react";
import { api } from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import type { HAEntity } from "@/lib/types";

function fmtChanged(ts: string | null) {
  if (!ts) return "—";
  try {
    const diff = Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    return `${Math.floor(diff / 3600)}h ago`;
  } catch {
    return "—";
  }
}

const USEFUL_DOMAINS = new Set([
  "sensor", "binary_sensor", "person", "device_tracker",
  "climate", "weather", "input_boolean", "switch", "light",
]);
const NOISY_DOMAINS = new Set([
  "camera", "automation", "scene", "script", "update", "button",
  "input_button", "image", "media_player", "tts", "stt", "todo",
  "calendar", "persistent_notification", "select", "text", "number",
]);

export function SensorBrowser() {
  const [domainFilter, setDomainFilter] = useState("All");
  const [areaFilter,   setAreaFilter]   = useState("All");
  const [query,        setQuery]        = useState("");
  const [showAll,      setShowAll]      = useState(false);
  const [refreshKey,   setRefreshKey]   = useState(0);

  const { data: entities = [], loading } = usePolling(
    () => api.haEntities(),
    15_000,
    [refreshKey],
  );

  const { data: areasData } = usePolling(() => api.haAreas(), 60_000, []);
  const areas = areasData?.areas ?? [];
  const byArea = areasData?.by_area ?? {};

  const allDomains = useMemo(() =>
    Array.from(new Set(entities.map((e) => e.domain))).sort(),
    [entities],
  );
  const usefulDomains = allDomains.filter((d) => !NOISY_DOMAINS.has(d));

  const areaEntitySet = useMemo(() => {
    if (areaFilter === "All") return null;
    const bucket = byArea[areaFilter] ?? {};
    const all = Object.values(bucket).flat();
    return new Set(all);
  }, [areaFilter, byArea]);

  const filtered: HAEntity[] = useMemo(() => {
    const q = query.toLowerCase();
    return entities.filter((e) => {
      if (!showAll && !USEFUL_DOMAINS.has(e.domain)) return false;
      if (domainFilter !== "All" && e.domain !== domainFilter) return false;
      if (areaEntitySet && !areaEntitySet.has(e.entity_id)) return false;
      if (q && !e.entity_id.toLowerCase().includes(q) && !e.friendly_name.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [entities, showAll, domainFilter, areaEntitySet, query]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Sensor Browser</h2>
          <p className="text-sm text-muted-foreground">
            {filtered.length} of {entities.length} entities
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
      <div className="flex flex-wrap gap-3 items-end">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">Domain</label>
          <select
            value={domainFilter}
            onChange={(e) => setDomainFilter(e.target.value)}
            className="rounded-lg border bg-background px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          >
            <option>All</option>
            {(showAll ? allDomains : usefulDomains).map((d) => (
              <option key={d}>{d}</option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">Area</label>
          <select
            value={areaFilter}
            onChange={(e) => setAreaFilter(e.target.value)}
            className="rounded-lg border bg-background px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          >
            <option>All</option>
            {areas.map((a) => <option key={a}>{a}</option>)}
          </select>
        </div>
        <div className="flex flex-col gap-1 flex-1 min-w-40">
          <label className="text-xs text-muted-foreground">Search</label>
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
            <input
              type="text"
              placeholder="entity_id or name..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full rounded-lg border bg-background pl-8 pr-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
            />
          </div>
        </div>
        <label className="flex items-center gap-1.5 text-sm cursor-pointer pb-1.5">
          <input
            type="checkbox"
            checked={showAll}
            onChange={(e) => setShowAll(e.target.checked)}
            className="rounded"
          />
          Show all types
        </label>
      </div>

      {/* Table */}
      {entities.length === 0 && loading ? (
        <div className="rounded-xl border bg-muted/30 p-8 text-center text-sm text-muted-foreground">
          Loading entities from Home Assistant...
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border bg-muted/30 p-8 text-center text-sm text-muted-foreground">
          No entities match the current filters.
        </div>
      ) : (
        <div className="rounded-xl border overflow-hidden">
          <div className="overflow-auto max-h-[calc(100vh-320px)]">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-muted/80 backdrop-blur-sm">
                <tr>
                  <th className="text-left px-3 py-2.5 font-medium text-muted-foreground w-[35%]">Entity ID</th>
                  <th className="text-left px-3 py-2.5 font-medium text-muted-foreground w-[25%]">Friendly Name</th>
                  <th className="text-left px-3 py-2.5 font-medium text-muted-foreground w-[20%]">State</th>
                  <th className="text-left px-3 py-2.5 font-medium text-muted-foreground w-[20%]">Last Changed</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((e, i) => (
                  <tr
                    key={e.entity_id}
                    className={`border-t ${i % 2 === 0 ? "bg-background" : "bg-muted/20"} hover:bg-primary/5 transition-colors`}
                  >
                    <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{e.entity_id}</td>
                    <td className="px-3 py-2 font-medium">{e.friendly_name || "—"}</td>
                    <td className="px-3 py-2">
                      <span className="font-mono">
                        {e.state}
                        {e.unit ? <span className="text-muted-foreground ml-1">{e.unit}</span> : null}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">{fmtChanged(e.last_changed)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="border-t bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            {filtered.length} entities shown
          </div>
        </div>
      )}
    </div>
  );
}
