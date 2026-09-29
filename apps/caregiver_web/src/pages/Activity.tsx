import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { BarChart, Bar, XAxis, ResponsiveContainer, Cell } from "recharts";
import { api } from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import { Timeline } from "@/components/Timeline";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { categoryStyle } from "@/lib/icons";
import { dayLabel } from "@/lib/format";
import type { ActivityCategory, ActivitySummary } from "@/lib/types";
import { cn } from "@/lib/utils";

function dayBounds(d: Date) {
  const start = new Date(d); start.setHours(0, 0, 0, 0);
  const end = new Date(d); end.setHours(23, 59, 59, 999);
  return { since: start.toISOString(), until: end.toISOString() };
}

function DayView({ profileId }: { profileId: string }) {
  const [offset, setOffset] = useState(0); // days back from today
  const date = new Date();
  date.setDate(date.getDate() - offset);
  const { since, until } = dayBounds(date);
  const { data, loading } = usePolling(
    () => api.activityLog(profileId, { since, limit: 200 }).then((evs) => evs.filter((e) => e.timestamp <= until)),
    15_000,
    [profileId, offset],
  );

  return (
    <div>
      <div className="mb-3 flex items-center justify-center gap-4">
        <button onClick={() => setOffset((o) => o + 1)} className="text-muted-foreground"><ChevronLeft className="size-5" /></button>
        <span className="text-sm font-semibold">{offset === 0 ? "Today" : dayLabel(date)}</span>
        <button onClick={() => setOffset((o) => Math.max(0, o - 1))} disabled={offset === 0} className="text-muted-foreground disabled:opacity-30"><ChevronRight className="size-5" /></button>
      </div>
      {loading && !data ? (
        <div className="space-y-3">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-12" />)}</div>
      ) : (
        <Timeline events={data ?? []} />
      )}
    </div>
  );
}

function CategoryBreakdown({ summary }: { summary: ActivitySummary }) {
  const entries = Object.entries(summary.by_category).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, v]) => v));
  return (
    <div className="space-y-2.5">
      {entries.map(([cat, count]) => {
        const style = categoryStyle[cat as ActivityCategory] ?? categoryStyle.unknown;
        return (
          <div key={cat} className="flex items-center gap-3">
            <span className="w-20 shrink-0 text-xs capitalize text-muted-foreground">{cat}</span>
            <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-muted">
              <div className={cn("h-full rounded-full", style.dot)} style={{ width: `${(count / max) * 100}%` }} />
            </div>
            <span className="w-6 shrink-0 text-right text-xs font-medium tabular-nums">{count}</span>
          </div>
        );
      })}
    </div>
  );
}

function HourChart({ summary }: { summary: ActivitySummary }) {
  const data = Array.from({ length: 24 }, (_, h) => ({ hour: h, count: summary.by_hour[String(h)] ?? 0 }));
  return (
    <ResponsiveContainer width="100%" height={120}>
      <BarChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
        <XAxis dataKey="hour" tickLine={false} axisLine={false} ticks={[0, 6, 12, 18]} tickFormatter={(h) => `${h}:00`} tick={{ fontSize: 10, fill: "var(--muted-foreground)" }} />
        <Bar dataKey="count" radius={[3, 3, 0, 0]}>
          {data.map((d) => (
            <Cell key={d.hour} fill={d.hour >= 8 && d.hour < 22 ? "var(--primary)" : "var(--muted)"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

const REGULARITY_STYLE: Record<string, string> = {
  high: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300",
  moderate: "bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300",
  low: "bg-red-100 text-red-700 dark:bg-red-950/50 dark:text-red-300",
};

function ClockRow({ label, stat }: { label: string; stat: { mean: string; spread_min: number } | null }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      {stat ? (
        <span className="text-sm font-medium tabular-nums">
          {stat.mean}
          <span className="ml-1.5 text-xs font-normal text-muted-foreground">± {stat.spread_min}m</span>
        </span>
      ) : (
        <span className="text-xs text-muted-foreground">not enough data</span>
      )}
    </div>
  );
}

function PatternsSection({ profileId, days }: { profileId: string; days: number }) {
  const { data } = usePolling(() => api.activityPatterns(profileId, days), 60_000, [profileId, days]);
  if (!data) return null;
  const rooms = Object.entries(data.time_in_room_pct);
  const maxPct = Math.max(1, ...rooms.map(([, v]) => v));
  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold">Daily routine</h3>
        {data.routine_regularity && (
          <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium capitalize", REGULARITY_STYLE[data.routine_regularity])}>
            {data.routine_regularity} regularity
          </span>
        )}
      </div>
      <div className="rounded-xl border bg-card p-4">
        <ClockRow label="Wakes up" stat={data.wake_time} />
        <ClockRow label="Goes to bed" stat={data.bed_time} />
        <ClockRow label="Breakfast" stat={data.breakfast_time} />
        <ClockRow label="Midday meal" stat={data.midday_meal_time} />
        <div className="my-2 border-t" />
        <div className="flex items-baseline justify-between py-1.5">
          <span className="text-xs text-muted-foreground">Night bathroom trips</span>
          <span className="text-sm font-medium tabular-nums">{data.night_bathroom_visits_per_night} <span className="text-xs font-normal text-muted-foreground">/ night</span></span>
        </div>
        <div className="flex items-baseline justify-between py-1.5">
          <span className="text-xs text-muted-foreground">Times left home</span>
          <span className="text-sm font-medium tabular-nums">{data.outings_per_day} <span className="text-xs font-normal text-muted-foreground">/ day</span></span>
        </div>
      </div>
      {rooms.length > 0 && (
        <div className="mt-4">
          <p className="mb-2 text-xs text-muted-foreground">Where time is spent</p>
          <div className="space-y-2">
            {rooms.map(([room, pct]) => (
              <div key={room} className="flex items-center gap-3">
                <span className="w-28 shrink-0 truncate text-xs text-muted-foreground">{room}</span>
                <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-muted">
                  <div className="h-full rounded-full bg-primary" style={{ width: `${(pct / maxPct) * 100}%` }} />
                </div>
                <span className="w-8 shrink-0 text-right text-xs font-medium tabular-nums">{pct}%</span>
              </div>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground">
            Share of logged activity by room{data.days_with_data ? ` · ${data.days_with_data} days with data` : ""}.
          </p>
        </div>
      )}
    </section>
  );
}

function RangeView({ profileId, days }: { profileId: string; days: number }) {
  const { data } = usePolling(() => api.activitySummary(profileId, days), 30_000, [profileId, days]);
  if (!data) return <Skeleton className="h-48 w-full" />;
  return (
    <div className="space-y-6">
      <div className="rounded-xl border bg-card p-4">
        <p className="text-xs font-medium text-muted-foreground">Total activities tracked</p>
        <p className="text-3xl font-bold">{data.total}</p>
        <p className="text-xs text-muted-foreground">over the last {days} days</p>
      </div>
      <PatternsSection profileId={profileId} days={days} />
      <section>
        <h3 className="mb-3 text-sm font-semibold">By category</h3>
        <CategoryBreakdown summary={data} />
      </section>
      <section>
        <h3 className="mb-1 text-sm font-semibold">Activity by time of day</h3>
        <p className="mb-2 text-xs text-muted-foreground">When the patient is most active</p>
        <HourChart summary={data} />
      </section>
    </div>
  );
}

export function Activity({ profileId }: { profileId: string }) {
  return (
    <div className="p-4">
      <Tabs defaultValue="day">
        <TabsList className="w-full">
          <TabsTrigger value="day" className="flex-1">Day</TabsTrigger>
          <TabsTrigger value="week" className="flex-1">Week</TabsTrigger>
          <TabsTrigger value="month" className="flex-1">Month</TabsTrigger>
        </TabsList>
        <TabsContent value="day" className="mt-4"><DayView profileId={profileId} /></TabsContent>
        <TabsContent value="week" className="mt-4"><RangeView profileId={profileId} days={7} /></TabsContent>
        <TabsContent value="month" className="mt-4"><RangeView profileId={profileId} days={30} /></TabsContent>
      </Tabs>
    </div>
  );
}
