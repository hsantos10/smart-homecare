import { useEffect, useState } from "react";
import { Sun } from "lucide-react";
import { api, onMockChange, usingMock } from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import { greeting } from "@/lib/format";
import { TopBar } from "@/components/TopBar";
import { CareModeBanner } from "@/components/CareMode";
import { useCareMode } from "@/hooks/useCareMode";
import { BottomNav, type TabKey } from "@/components/BottomNav";
import { Summary } from "@/pages/Summary";
import { Activity } from "@/pages/Activity";
import { RoomPage } from "@/pages/RoomPage";
import { Alerts } from "@/pages/Alerts";
import { Health } from "@/pages/Health";
import { Environment } from "@/pages/Environment";
import { AdminShell } from "@/pages/admin/AdminShell";

const PROFILE_ID = "patient-001";

// True inside the Capacitor Android shell. There the app is served from the APK, so
// there's no dev proxy and no same-origin API — the server address must be settable
// in-app. Also true when the API is unreachable, so the web build can recover too.
const IS_NATIVE = typeof window !== "undefined" &&
  Boolean((window as unknown as { Capacitor?: { isNativePlatform?: () => boolean } })
    .Capacitor?.isNativePlatform?.());

const TITLES: Record<TabKey, string> = {
  summary: "Smart Home(care)",
  alerts: "Alerts",
  room: "Room",
  activity: "Activity",
  health: "Health",
  environment: "Environment",
};

// Allow deep-linking to a tab via ?tab=activity (also handy for the Android webview).
function initialTab(): TabKey {
  const t = new URLSearchParams(window.location.search).get("tab");
  return t && t in TITLES ? (t as TabKey) : "summary";
}

function isAdminMode(): boolean {
  return new URLSearchParams(window.location.search).get("mode") === "admin";
}

export default function App() {
  if (isAdminMode()) return <AdminShell />;

  const [tab, setTab] = useState<TabKey>(initialTab);
  const [mock, setMock] = useState(usingMock());
  const { data: status } = usePolling(() => api.currentStatus(PROFILE_ID), 10_000, []);
  const { data: profiles } = usePolling(() => api.profiles(), 60_000, []);
  const care = useCareMode(PROFILE_ID);

  useEffect(() => onMockChange(setMock), []);

  const caregiver = profiles?.find((p) => p.profile_id === PROFILE_ID)?.caregiver_name ?? "there";
  const alertCount = status?.active_alerts ?? 0;

  return (
    <div className="flex min-h-screen justify-center bg-neutral-100 dark:bg-neutral-950">
      <div className="flex h-screen w-full max-w-[440px] flex-col overflow-hidden bg-background shadow-xl">
        <TopBar title={TITLES[tab]} alertCount={alertCount} onBell={() => setTab("alerts")}
                showServerButton={IS_NATIVE || mock} />

        {mock && (
          <div className="bg-amber-100 px-4 py-1.5 text-center text-[11px] font-medium text-amber-800 dark:bg-amber-950/60 dark:text-amber-300">
            Showing demo data — backend API not reachable
          </div>
        )}
        <CareModeBanner mode={care.mode} onAlone={() => care.setMode("alone", null)} />

        <main className="flex-1 overflow-y-auto overscroll-contain">
          {tab === "summary" && (
            <>
              <div className="flex items-center gap-3 px-4 pt-4">
                <span className="flex size-9 items-center justify-center rounded-full bg-amber-100 text-amber-500 dark:bg-amber-950/60">
                  <Sun className="size-5" />
                </span>
                <div>
                  <p className="text-base font-semibold leading-tight">
                    {greeting()}, {caregiver}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {status?.patient_name ?? "Patient"} ·{" "}
                    {status?.risk_level === "ok" ? "Everything is up to date" : "Needs your attention"}
                  </p>
                </div>
              </div>
              <Summary profileId={PROFILE_ID} onNavigate={setTab}
                       patientName={status?.patient_name ?? "Patient"}
                       careMode={care.mode} setCareMode={care.setMode} />
            </>
          )}
          {tab === "alerts" && <Alerts profileId={PROFILE_ID} />}
          {tab === "room" && <RoomPage profileId={PROFILE_ID} />}
          {tab === "activity" && <Activity profileId={PROFILE_ID} />}
          {tab === "health" && <Health />}
          {tab === "environment" && <Environment profileId={PROFILE_ID} />}
        </main>

        <BottomNav active={tab} onChange={setTab} alertCount={alertCount} />
      </div>
    </div>
  );
}
