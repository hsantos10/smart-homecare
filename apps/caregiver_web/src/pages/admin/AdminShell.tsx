import { useState } from "react";
import { api } from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import {
  Watch, ShieldAlert, LayoutDashboard, ArrowLeft,
  Activity, Wifi, WifiOff, Bell, Radio, History,
} from "lucide-react";
import { WatchConfigAdmin } from "./WatchConfigAdmin";
import { RulesAdmin } from "./RulesAdmin";
import { AlertsAdmin } from "./AlertsAdmin";
import { SensorBrowser } from "./SensorBrowser";
import { SensorHistory } from "./SensorHistory";

type AdminTab = "rules" | "alerts" | "sensors" | "history" | "watch";

const NAV: { key: AdminTab; label: string; icon: React.ElementType; description: string }[] = [
  { key: "rules",   label: "Alert Rules",     icon: ShieldAlert,  description: "Create and manage alert rules" },
  { key: "alerts",  label: "Alert History",   icon: Bell,         description: "Query and acknowledge alerts" },
  { key: "sensors", label: "Sensor Browser",  icon: Radio,        description: "Live HA entity state" },
  { key: "history", label: "Sensor History",  icon: History,      description: "Historical sensor charts" },
  { key: "watch",   label: "Watch Config",    icon: Watch,        description: "Map Pixel Watch entities" },
];

const PROFILE_ID = "patient-001";

export function AdminShell() {
  const [tab, setTab] = useState<AdminTab>(() => {
    const t = new URLSearchParams(window.location.search).get("tab") as AdminTab | null;
    const valid: AdminTab[] = ["rules", "alerts", "sensors", "history", "watch"];
    return t && valid.includes(t) ? t : "rules";
  });
  const { data: haEntities, loading: haLoading } = usePolling(() => api.haEntities(), 15_000, []);
  const haStatus = haLoading ? "unknown" : (haEntities && haEntities.length > 0 ? "ok" : "error");


  function goBack() {
    window.location.href = window.location.pathname;
  }

  return (
    <div className="min-h-screen bg-neutral-100 dark:bg-neutral-950">
      <div className="mx-auto max-w-5xl">
        {/* Top bar */}
        <header className="flex items-center gap-4 border-b bg-background px-6 py-4 shadow-sm">
          <button
            onClick={goBack}
            className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium hover:bg-muted transition-colors"
          >
            <ArrowLeft className="size-4" />
            Patient View
          </button>
          <div className="flex items-center gap-2">
            <span className="flex size-8 items-center justify-center rounded-lg bg-primary/10">
              <LayoutDashboard className="size-4 text-primary" />
            </span>
            <div>
              <p className="text-sm font-semibold leading-tight">DARI Admin</p>
              <p className="text-xs text-muted-foreground">Patient A · Smart Homecare</p>
            </div>
          </div>
          <div className="ml-auto flex items-center gap-1.5 text-xs">
            {haStatus === "ok"
              ? <><Wifi className="size-3.5 text-emerald-500" /><span className="text-emerald-600 dark:text-emerald-400">HA connected · {haEntities!.length} entities</span></>
              : haStatus === "error"
              ? <><WifiOff className="size-3.5 text-red-500" /><span className="text-red-500">HA unreachable</span></>
              : <><WifiOff className="size-3.5 text-muted-foreground" /><span className="text-muted-foreground">Checking HA...</span></>
            }
          </div>
        </header>

        <div className="flex gap-0">
          {/* Sidebar */}
          <nav className="w-56 shrink-0 border-r bg-background min-h-[calc(100vh-65px)]">
            <div className="space-y-1 p-3">
              {NAV.map(({ key, label, icon: Icon, description }) => (
                <button
                  key={key}
                  onClick={() => setTab(key)}
                  className={`w-full rounded-xl px-3 py-2.5 text-left transition-colors ${
                    tab === key
                      ? "bg-primary/10 text-primary"
                      : "text-foreground hover:bg-muted"
                  }`}
                >
                  <div className="flex items-center gap-2.5">
                    <Icon className="size-4 shrink-0" />
                    <div>
                      <p className="text-sm font-medium leading-tight">{label}</p>
                      <p className="text-[10px] text-muted-foreground leading-tight">{description}</p>
                    </div>
                  </div>
                </button>
              ))}
            </div>

            <div className="border-t p-3">
              <div className="rounded-xl bg-muted/50 p-3">
                <div className="flex items-center gap-2">
                  <Activity className="size-3.5 text-muted-foreground" />
                  <p className="text-xs font-medium">API</p>
                </div>
                <p className="mt-1 text-[10px] text-muted-foreground">
                  FastAPI · port 8000
                </p>
                <p className="text-[10px] text-muted-foreground">
                  HA · address from HA_URL in .env
                </p>
              </div>
            </div>
          </nav>

          {/* Main content */}
          <main className="flex-1 p-6">
            <ErrorBoundary key={tab}>
              {tab === "rules"   && <RulesAdmin       profileId={PROFILE_ID} />}
              {tab === "alerts"  && <AlertsAdmin      profileId={PROFILE_ID} />}
              {tab === "sensors" && <SensorBrowser />}
              {tab === "history" && <SensorHistory />}
              {tab === "watch"   && <WatchConfigAdmin profileId={PROFILE_ID} />}
            </ErrorBoundary>
          </main>
        </div>
      </div>
    </div>
  );
}
