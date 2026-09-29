import { ClipboardList, Bell, Home, Footprints, HeartPulse, CloudSun } from "lucide-react";
import { cn } from "@/lib/utils";

export type TabKey = "summary" | "alerts" | "room" | "activity" | "health" | "environment";

const TABS: { key: TabKey; label: string; icon: typeof Home }[] = [
  { key: "summary", label: "Summary", icon: ClipboardList },
  { key: "alerts", label: "Alerts", icon: Bell },
  { key: "room", label: "Room", icon: Home },
  { key: "activity", label: "Activity", icon: Footprints },
  { key: "health", label: "Health", icon: HeartPulse },
  { key: "environment", label: "Environment", icon: CloudSun },
];

export function BottomNav({
  active,
  onChange,
  alertCount = 0,
}: {
  active: TabKey;
  onChange: (k: TabKey) => void;
  alertCount?: number;
}) {
  return (
    <nav className="sticky bottom-0 z-20 grid grid-cols-6 border-t bg-background/90 backdrop-blur-md">
      {TABS.map(({ key, label, icon: Icon }) => {
        const isActive = active === key;
        return (
          <button
            key={key}
            onClick={() => onChange(key)}
            className={cn(
              "relative flex flex-col items-center gap-1 py-2 text-[10px] font-medium transition-colors",
              isActive ? "text-primary" : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className={cn("size-5", isActive && "stroke-[2.5]")} />
            <span>{label}</span>
            {key === "alerts" && alertCount > 0 && (
              <span className="absolute right-1/4 top-1 size-2 rounded-full bg-red-500" />
            )}
          </button>
        );
      })}
    </nav>
  );
}
