import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "edu.tamu.dari.caregiver",
  appName: "DARI Caregiver",
  webDir: "dist",
  android: {
    // The DARI API is served over plain HTTP on the tailnet (http://<tailscale-ip>:8000).
    // Android blocks cleartext by default, so without this the packaged app can only ever
    // reach the API over HTTPS. Revisit once the API terminates TLS.
    allowMixedContent: true,
  },
  server: {
    androidScheme: "https",
    cleartext: true,
  },
};

export default config;
