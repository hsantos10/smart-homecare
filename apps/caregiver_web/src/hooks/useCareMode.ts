import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { CareMode, CareModeKey } from "@/lib/types";

/** Shared care-mode state: polled so another caregiver's change shows up, and so an
 *  expired "with others" timer flips the UI back to "alone". */
export function useCareMode(profileId: string) {
  const [mode, setModeState] = useState<CareMode | undefined>();

  const refresh = useCallback(() => {
    api.careMode(profileId).then(setModeState);
  }, [profileId]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 30_000);
    return () => clearInterval(id);
  }, [refresh]);

  const setMode = useCallback(async (m: CareModeKey, minutes: number | null) => {
    setModeState(await api.setCareMode(profileId, m, minutes));
  }, [profileId]);

  return { mode, setMode, refresh };
}
