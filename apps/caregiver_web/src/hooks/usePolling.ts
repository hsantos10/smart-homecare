import { useEffect, useRef, useState } from "react";

/**
 * Polls an async fetcher on an interval and tracks loading/error/data.
 * Used by every screen so live data stays fresh without manual refresh.
 */
export function usePolling<T>(fetcher: () => Promise<T>, intervalMs = 10_000, deps: unknown[] = []) {
  const [data, setData] = useState<T | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const savedFetcher = useRef(fetcher);

  useEffect(() => {
    savedFetcher.current = fetcher;
  }, [fetcher]);

  useEffect(() => {
    let alive = true;
    const run = async () => {
      try {
        const result = await savedFetcher.current();
        if (alive) setData(result);
      } finally {
        if (alive) setLoading(false);
      }
    };
    run();
    let id: ReturnType<typeof setInterval> | undefined;
    const start = () => {
      if (id == null) id = setInterval(run, intervalMs);
    };
    const stop = () => {
      if (id != null) {
        clearInterval(id);
        id = undefined;
      }
    };
    // Only poll while the page is visible — lets the view go idle in the background
    // (and saves battery on mobile / the Android client).
    const onVisibility = () => (document.hidden ? stop() : (run(), start()));
    document.addEventListener("visibilitychange", onVisibility);
    if (!document.hidden) start();
    return () => {
      alive = false;
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, ...deps]);

  return { data, loading };
}
