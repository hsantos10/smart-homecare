import { useState, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import { User, Clock, Thermometer, Droplets, RefreshCw, VideoOff, X, Maximize2 } from "lucide-react";
import { api, getApiBase } from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import { activityIcon, categoryStyle } from "@/lib/icons";
import { clockTime, timeAgo } from "@/lib/format";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

function CameraModal({ entityId, name, onClose }: { entityId: string; name: string; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex flex-col bg-black"
      onClick={onClose}
    >
      <div
        className="flex items-center justify-between px-4 py-3"
        onClick={(e) => e.stopPropagation()}
      >
        <span className="text-sm font-medium text-white">{name}</span>
        <button onClick={onClose} className="text-white/70 hover:text-white">
          <X className="size-5" />
        </button>
      </div>
      <div className="flex flex-1 items-center justify-center" onClick={(e) => e.stopPropagation()}>
        <img
          src={`${getApiBase()}/api/camera_stream/${entityId}`}
          alt={name}
          className="max-h-full max-w-full object-contain"
        />
      </div>
    </div>,
    document.body,
  );
}

function CameraFeed({ entityId, name }: { entityId: string; name: string }) {
  const [tick, setTick] = useState(0);
  const [error, setError] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const refresh = useCallback(() => { setTick((t) => t + 1); setError(false); }, []);

  useEffect(() => {
    const id = setInterval(refresh, 5_000);
    return () => clearInterval(id);
  }, [refresh]);

  return (
    <>
      <div className="overflow-hidden rounded-xl border bg-black">
        <div className="flex items-center justify-between bg-card px-3 py-2">
          <span className="text-xs font-medium">{name}</span>
          <div className="flex items-center gap-2">
            <button onClick={refresh} className="text-muted-foreground hover:text-foreground">
              <RefreshCw className="size-3.5" />
            </button>
            <button onClick={() => setExpanded(true)} className="text-muted-foreground hover:text-foreground">
              <Maximize2 className="size-3.5" />
            </button>
          </div>
        </div>
        <button className="block w-full" onClick={() => setExpanded(true)}>
          {error ? (
            <div className="flex aspect-video items-center justify-center gap-2 text-xs text-muted-foreground">
              <VideoOff className="size-4" /> Feed unavailable
            </div>
          ) : (
            <img
              // Absolute: inside the Android shell the page origin is https://localhost,
              // so a bare /api/... path would hit the bundle, not the API.
              src={`${getApiBase()}/api/camera_proxy/${entityId}?_t=${tick}`}
              alt={name}
              className="aspect-video w-full object-contain"
              onError={() => setError(true)}
            />
          )}
        </button>
      </div>
      {expanded && <CameraModal entityId={entityId} name={name} onClose={() => setExpanded(false)} />}
    </>
  );
}

// HA has a single combined area called "Bedroom Bathroom" — expand it into two display rooms.
const SPLIT_AREAS: Record<string, string[]> = {
  "bedroom bathroom": ["Bedroom", "Bathroom"],
};

function expandRooms(zones: Record<string, boolean>): { label: string; haArea: string }[] {
  const result: { label: string; haArea: string }[] = [];
  const seenLabels = new Set<string>();
  const areaNames = new Set(Object.keys(zones).map((a) => a.toLowerCase()));
  for (const area of Object.keys(zones)) {
    const splits = SPLIT_AREAS[area.toLowerCase()];
    if (splits) {
      // Skip a split label if it collides with a label already added — most often
      // because the home ALSO has a real, separate area of that same name
      // (e.g. a literal "Bedroom" area alongside the combined "Bedroom Bathroom").
      splits
        .filter((label) => !seenLabels.has(label.toLowerCase()) && !areaNames.has(label.toLowerCase()))
        .forEach((label) => {
          result.push({ label, haArea: area });
          seenLabels.add(label.toLowerCase());
        });
    } else if (!seenLabels.has(area.toLowerCase())) {
      result.push({ label: area, haArea: area });
      seenLabels.add(area.toLowerCase());
    }
  }
  return result;
}

// Match a camera to a display room by area name OR entity_id prefix (e.g. camera.bedroom_* → Bedroom).
function cameraMatchesRoom(cam: { entity_id: string; area: string }, roomLabel: string): boolean {
  const label = roomLabel.toLowerCase();
  if (cam.area.toLowerCase() === label) return true;
  // Check if the HA area splits contain this label
  const splitEntry = Object.entries(SPLIT_AREAS).find(([, labels]) =>
    labels.map((l) => l.toLowerCase()).includes(label),
  );
  if (splitEntry && cam.area.toLowerCase() === splitEntry[0]) {
    // Camera is in the combined area — match by entity_id keyword
    const eid = cam.entity_id.toLowerCase();
    return eid.includes(label.replace(" ", "_")) || eid.includes(label.replace(" ", ""));
  }
  return false;
}

export function RoomPage({ profileId }: { profileId: string }) {
  const { data: status } = usePolling(() => api.currentStatus(profileId), 5_000, [profileId]);
  const { data: env } = usePolling(() => api.environment(profileId), 15_000, [profileId]);
  const { data: cameras } = usePolling(() => api.cameras(), 60_000, []);
  const [selected, setSelected] = useState<string | null>(null);

  if (!status) return <div className="p-4"><Skeleton className="h-64 w-full" /></div>;

  const displayRooms = expandRooms(status.presence_by_zone);

  // Map current_zone (HA area) to a display label
  const currentLabel = status.current_zone
    ? (SPLIT_AREAS[status.current_zone.toLowerCase()]?.[0] ?? status.current_zone)
    : null;

  const roomLabel = selected ?? currentLabel ?? displayRooms[0]?.label ?? "Living room";
  const roomEntry = displayRooms.find((r) => r.label === roomLabel) ?? displayRooms[0];
  const haArea = roomEntry?.haArea ?? roomLabel;

  const occupied = status.presence_by_zone[haArea];
  const isCurrent = status.home && status.current_zone?.toLowerCase() === haArea.toLowerCase();
  const roomEnv = (env ?? []).filter((e) => e.area?.toLowerCase() === haArea.toLowerCase());
  // The engine only computes ONE specific activity label, for its single current_zone
  // (multiple rooms can independently show presence at once when more than one person
  // is in the house). A room with presence but not the current_zone
  // has someone/something there, just not a specific inferred activity — say so, don't
  // claim "Not here" while Presence right below says "Detected".
  const activityText = isCurrent ? status.activity_label : occupied ? "Present" : "Not here";
  const Icon = activityIcon(isCurrent ? status.activity_icon : occupied ? "footprints" : "user-x");
  const cat = isCurrent
    ? (categoryStyle[status.activity_category] ?? categoryStyle.unknown)
    : occupied
      ? categoryStyle.mobility
      : categoryStyle.unknown;

  return (
    <div className="space-y-4 p-4">
      {/* Room tabs */}
      <div className="flex gap-2 overflow-x-auto pb-1">
        {displayRooms.map(({ label, haArea: area }) => (
          <button
            key={label}
            onClick={() => setSelected(label)}
            className={cn(
              "flex items-center gap-1.5 whitespace-nowrap rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
              label === roomLabel ? "border-primary bg-primary text-primary-foreground" : "bg-card text-muted-foreground",
            )}
          >
            <span className={cn("size-1.5 rounded-full", status.presence_by_zone[area] ? "bg-emerald-500" : "bg-muted-foreground/40")} />
            {label}
          </button>
        ))}
      </div>

      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold">{roomLabel}</h2>
        <span className="flex items-center gap-1 text-xs text-muted-foreground">
          <span className="size-1.5 rounded-full bg-emerald-500" /> Live
        </span>
      </div>

      {/* Current activity */}
      <div className={cn("rounded-2xl border p-4", isCurrent || occupied ? cat.bg : "bg-card")}>
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Current activity</p>
        <div className="mt-1 flex items-center gap-3">
          <span className={cn("flex size-11 items-center justify-center rounded-xl bg-background/70", isCurrent || occupied ? cat.fg : "text-muted-foreground")}>
            <Icon className="size-6" />
          </span>
          <div>
            <p className="text-xl font-bold">{activityText}</p>
            {isCurrent && status.since && (
              <p className="text-xs text-muted-foreground">Since {clockTime(status.since)}</p>
            )}
          </div>
        </div>
      </div>

      {/* Presence + last movement */}
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-xl border bg-card p-4">
          <div className="flex items-center gap-2 text-muted-foreground"><User className="size-4" /><span className="text-xs">Presence</span></div>
          <p className={cn("mt-1 text-base font-semibold", occupied ? "text-emerald-600" : "text-muted-foreground")}>
            {occupied ? "Detected" : "Empty"}
          </p>
        </div>
        <div className="rounded-xl border bg-card p-4">
          <div className="flex items-center gap-2 text-muted-foreground"><Clock className="size-4" /><span className="text-xs">Last movement</span></div>
          <p className="mt-1 text-base font-semibold">{timeAgo(status.last_movement)}</p>
        </div>
      </div>

      {/* Sensors */}
      {roomEnv.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-semibold">Sensors</h3>
          <div className="grid grid-cols-2 gap-3">
            {roomEnv.map((e) => (
              <div key={e.entity_id} className="rounded-xl border bg-card p-4">
                <div className="flex items-center gap-2 text-muted-foreground">
                  {e.kind === "humidity" ? <Droplets className="size-4" /> : <Thermometer className="size-4" />}
                  <span className="truncate text-xs">{e.kind === "humidity" ? "Humidity" : e.kind === "temperature" ? "Temperature" : e.name}</span>
                </div>
                <p className="mt-1 text-lg font-semibold">{e.value ?? "—"} {e.unit}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Camera feeds for this room */}
      {(() => {
        const roomCams = (cameras ?? []).filter((c) => cameraMatchesRoom(c, roomLabel));
        if (!cameras) return null; // still loading
        if (roomCams.length === 0) return null; // no cameras in this room
        return (
          <section>
            <h3 className="mb-2 text-sm font-semibold">Camera</h3>
            <div className="space-y-3">
              {roomCams.map((c) => (
                <CameraFeed key={c.entity_id} entityId={c.entity_id} name={c.friendly_name} />
              ))}
            </div>
          </section>
        );
      })()}
    </div>
  );
}
