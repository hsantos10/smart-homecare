// Lets the user point the app at the DARI API at runtime.
//
// This exists for the packaged Android app: the APK ships with a build-time default, but
// the server's address changes (VPN address, a different home), and a caregiver cannot
// rebuild an APK. Saving here writes to localStorage, which api.ts reads on next request.
import { useState } from "react";
import { Server, Check, X, Loader2 } from "lucide-react";
import { getApiBase, setApiBase, probeApiBase } from "@/lib/api";

type Probe = "idle" | "testing" | "ok" | "fail";

export function ServerSettings({ onClose }: { onClose: () => void }) {
  const [url, setUrl] = useState(getApiBase());
  const [probe, setProbe] = useState<Probe>("idle");

  async function test() {
    setProbe("testing");
    setProbe((await probeApiBase(url)) ? "ok" : "fail");
  }

  function save() {
    setApiBase(url);
    // A full reload is the honest way to re-fetch every screen against the new base —
    // the polling hooks hold results from the old server otherwise.
    window.location.reload();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 sm:items-center"
         onClick={onClose}>
      <div className="w-full max-w-md rounded-t-2xl bg-background p-5 sm:rounded-2xl"
           onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center gap-2">
          <Server className="size-5 text-muted-foreground" />
          <h2 className="text-base font-semibold">Server address</h2>
        </div>

        <p className="mb-3 text-sm text-muted-foreground">
          Where the DARI API is running. On a phone this must be an address the device can
          reach &mdash; its LAN or VPN address, not <code>127.0.0.1</code>.
        </p>

        <input
          value={url}
          onChange={(e) => { setUrl(e.target.value); setProbe("idle"); }}
          placeholder="http://<server-address>:8000"
          inputMode="url"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          className="w-full rounded-lg border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
        />

        {probe === "ok" && (
          <p className="mt-2 flex items-center gap-1.5 text-sm text-green-600">
            <Check className="size-4" /> Reached the API.
          </p>
        )}
        {probe === "fail" && (
          <p className="mt-2 flex items-center gap-1.5 text-sm text-red-600">
            <X className="size-4" /> No response. Check the address, that the API is
            running, and that this device can reach it (same network or VPN).
          </p>
        )}

        <div className="mt-5 flex gap-2">
          <button onClick={test} disabled={probe === "testing"}
                  className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-medium disabled:opacity-60">
            {probe === "testing" && <Loader2 className="size-4 animate-spin" />}
            Test
          </button>
          <button onClick={save}
                  className="flex-1 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground">
            Save &amp; reload
          </button>
        </div>

        <button onClick={onClose}
                className="mt-3 w-full py-2 text-sm text-muted-foreground">
          Cancel
        </button>
      </div>
    </div>
  );
}
