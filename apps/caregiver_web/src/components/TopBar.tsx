import { useState } from "react";
import { Bell, Settings, Server } from "lucide-react";
import { ServerSettings } from "./ServerSettings";

export function TopBar({
  title,
  alertCount = 0,
  onBell,
  showServerButton = false,
}: {
  title: string;
  alertCount?: number;
  onBell?: () => void;
  /** Show the server-address button — on by default in the packaged app, where there
   *  is no Vite proxy and the API address has to be set by hand. */
  showServerButton?: boolean;
}) {
  const [serverOpen, setServerOpen] = useState(false);

  function openAdmin() {
    window.location.href = `${window.location.pathname}?mode=admin`;
  }

  return (
    <>
      <header className="sticky top-0 z-20 flex items-center justify-between border-b bg-background/80 px-4 py-3 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <button onClick={openAdmin} className="text-muted-foreground hover:text-foreground transition-colors" aria-label="Admin">
            <Settings className="size-5" />
          </button>
          {showServerButton && (
            <button onClick={() => setServerOpen(true)}
                    className="text-muted-foreground hover:text-foreground transition-colors"
                    aria-label="Server address">
              <Server className="size-5" />
            </button>
          )}
        </div>
        <h1 className="text-base font-semibold tracking-tight">{title}</h1>
        <button onClick={onBell} className="relative text-muted-foreground" aria-label="Alerts">
          <Bell className="size-5" />
          {alertCount > 0 && (
            <span className="absolute -right-1.5 -top-1.5 flex size-4 items-center justify-center rounded-full bg-red-500 text-[10px] font-bold text-white">
              {alertCount}
            </span>
          )}
        </button>
      </header>

      {serverOpen && <ServerSettings onClose={() => setServerOpen(false)} />}
    </>
  );
}
