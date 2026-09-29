// Care mode: is the person home alone, or with others?
//
// The house sensors can't tell people apart, so with a caregiver or visitor present the
// movement-based alerts (night wandering, inactivity, long bathroom stay) would fire on
// someone else. "With others" pauses those; falls, doors, air quality and heart rate stay
// on. The risky mistake is leaving "with others" on after everyone has gone, so it
// defaults to a time limit, and a banner stays up on every screen while it's active.
import { useEffect, useState } from "react";
import { User, Users, Clock, X, Loader2, PauseCircle } from "lucide-react";
import { api } from "@/lib/api";
import { clockTime } from "@/lib/format";
import type { CareMode, CareModeKey } from "@/lib/types";
import { cn } from "@/lib/utils";

const DURATIONS: { label: string; minutes: number | null }[] = [
  { label: "1 hour", minutes: 60 },
  { label: "2 hours", minutes: 120 },
  { label: "4 hours", minutes: 240 },
  { label: "8 hours", minutes: 480 },
  { label: "Until I switch back", minutes: null },
];

function untilText(m: CareMode): string {
  return m.until ? `until ${clockTime(m.until)}` : "until you switch back";
}

/** Amber strip under the top bar on every screen while "with others" is on. */
export function CareModeBanner({ mode, onAlone }: { mode?: CareMode; onAlone: () => void }) {
  if (mode?.mode !== "with_others") return null;
  const n = mode.paused_rules.length;
  return (
    <div className="flex items-center gap-2 bg-amber-100 px-4 py-2 text-xs text-amber-900 dark:bg-amber-950/60 dark:text-amber-200">
      <Users className="size-4 shrink-0" />
      <p className="min-w-0 flex-1 leading-tight">
        <span className="font-semibold">With others</span> {untilText(mode)}
        {n > 0 && <> · {n} movement alert{n > 1 ? "s" : ""} paused</>}
      </p>
      <button onClick={onAlone}
              className="shrink-0 rounded-full bg-amber-900/10 px-2.5 py-1 font-semibold hover:bg-amber-900/20 dark:bg-amber-200/10">
        Home alone
      </button>
    </div>
  );
}

/** Two-option switch on the Summary screen. */
export function CareModeCard({ profileId, patientName, mode, setMode }: {
  profileId: string;
  patientName: string;
  mode?: CareMode;
  setMode: (m: CareModeKey, minutes: number | null) => Promise<void>;
}) {
  const [sheetOpen, setSheetOpen] = useState(false);
  const current = mode?.mode ?? "alone";

  const options: { key: CareModeKey; label: string; hint: string; Icon: typeof User }[] = [
    { key: "alone", label: "Home alone", hint: "All alerts on", Icon: User },
    { key: "with_others", label: "With others", hint: "Movement alerts paused", Icon: Users },
  ];

  return (
    <section className="rounded-2xl border bg-card p-4">
      <h3 className="text-sm font-semibold">Who's home with {patientName}?</h3>
      <div role="radiogroup" aria-label="Care mode" className="mt-3 grid grid-cols-2 gap-2">
        {options.map(({ key, label, hint, Icon }) => {
          const selected = current === key;
          return (
            <button
              key={key}
              role="radio"
              aria-checked={selected}
              onClick={() => (key === "alone" ? setMode("alone", null) : setSheetOpen(true))}
              className={cn(
                "flex flex-col items-start gap-1 rounded-xl border-2 p-3 text-left transition-colors",
                selected && key === "alone" && "border-emerald-500 bg-emerald-50 dark:bg-emerald-950/30",
                selected && key === "with_others" && "border-amber-500 bg-amber-50 dark:bg-amber-950/30",
                !selected && "border-transparent bg-muted/50 hover:bg-muted",
              )}
            >
              <Icon className={cn("size-5",
                selected ? (key === "alone" ? "text-emerald-600" : "text-amber-600") : "text-muted-foreground")} />
              <span className="text-sm font-semibold">{label}</span>
              <span className="text-xs text-muted-foreground">{hint}</span>
            </button>
          );
        })}
      </div>
      {mode?.mode === "with_others" && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
          <Clock className="size-3.5" />
          {mode.until ? `Switches back to home alone at ${clockTime(mode.until)}` : "Stays on until you switch back"}
          <button onClick={() => setSheetOpen(true)} className="ml-auto font-medium text-primary">Change</button>
        </p>
      )}

      {sheetOpen && (
        <WithOthersSheet profileId={profileId} patientName={patientName}
                         onCancel={() => setSheetOpen(false)}
                         onConfirm={async (minutes) => { await setMode("with_others", minutes); setSheetOpen(false); }} />
      )}
    </section>
  );
}

/** Confirmation: how long, and exactly which alerts pause. */
function WithOthersSheet({ profileId, patientName, onCancel, onConfirm }: {
  profileId: string;
  patientName: string;
  onCancel: () => void;
  onConfirm: (minutes: number | null) => Promise<void>;
}) {
  const [minutes, setMinutes] = useState<number | null>(120);
  const [preview, setPreview] = useState<CareMode | undefined>();
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.previewCareMode(profileId, "with_others").then(setPreview);
  }, [profileId]);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 sm:items-center" onClick={onCancel}>
      <div className="w-full max-w-md rounded-t-2xl bg-background p-5 sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center gap-2">
          <Users className="size-5 text-amber-600" />
          <h2 className="flex-1 text-base font-semibold">Someone is with {patientName}</h2>
          <button onClick={onCancel} aria-label="Close" className="text-muted-foreground"><X className="size-5" /></button>
        </div>

        <p className="text-sm text-muted-foreground">
          The sensors can't tell people apart, so while others are home these alerts pause:
        </p>
        <ul className="mt-2 space-y-1">
          {!preview
            ? <li className="text-sm text-muted-foreground">Loading…</li>
            : preview.paused_rules.map((r) => (
                <li key={r} className="flex items-center gap-2 text-sm">
                  <PauseCircle className="size-4 shrink-0 text-amber-600" /> {r}
                </li>
              ))}
        </ul>
        {preview && (
          <p className="mt-2 text-xs text-muted-foreground">
            {preview.active_rules} alerts stay on, including falls, doors, air quality and heart rate.
          </p>
        )}

        <p className="mt-4 text-sm font-medium">Switch back to home alone after</p>
        <div className="mt-2 flex flex-wrap gap-2">
          {DURATIONS.map((d) => (
            <button key={d.label} onClick={() => setMinutes(d.minutes)}
                    className={cn("rounded-full border px-3 py-1.5 text-xs font-medium",
                      minutes === d.minutes ? "border-amber-500 bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
                                            : "hover:bg-muted")}>
              {d.label}
            </button>
          ))}
        </div>
        {minutes === null && (
          <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
            Remember to switch back when {patientName} is alone. Until then, paused alerts won't reach you.
          </p>
        )}

        <div className="mt-5 flex gap-2">
          <button onClick={onCancel} className="flex-1 rounded-lg border px-4 py-2.5 text-sm font-medium hover:bg-muted">
            Cancel
          </button>
          <button
            disabled={saving}
            onClick={async () => { setSaving(true); try { await onConfirm(minutes); } finally { setSaving(false); } }}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-amber-500 px-4 py-2.5 text-sm font-semibold text-white hover:bg-amber-600 disabled:opacity-60"
          >
            {saving && <Loader2 className="size-4 animate-spin" />} Start
          </button>
        </div>
      </div>
    </div>
  );
}
