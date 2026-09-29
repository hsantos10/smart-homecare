// Floor plan shown on the Summary / Room screens: the image, its pixel size, and one
// box per Home Assistant area (names must match the HA area names). Replace this file
// and the image with your own home's plan.
import floorplan from "@/assets/floorplan.png";

export const FLOORPLAN_URL: string = floorplan;

export const CANVAS = { width: 1200, height: 800 };

export const ROOMS: { name: string; x0: number; y0: number; x1: number; y1: number }[] = [
  { name: "Bedroom", x0: 40, y0: 40, x1: 440, y1: 460 },
  { name: "Bedroom Bathroom", x0: 40, y0: 460, x1: 440, y1: 760 },
  { name: "Living room", x0: 440, y0: 40, x1: 900, y1: 760 },
  { name: "Kitchen", x0: 900, y0: 40, x1: 1160, y1: 400 },
  { name: "Study room", x0: 900, y0: 400, x1: 1160, y1: 760 },
];
