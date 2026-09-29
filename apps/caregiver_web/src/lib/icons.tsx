// Maps backend icon hints + categories to lucide icons and a colour palette.
// The backend sends icon NAMES (not React) so the same hints work for Android too.
import {
  Activity, AlertTriangle, Armchair, Bath, Bed, Coffee, CookingPot, DoorOpen,
  Footprints, Home, LampDesk, LogIn, LogOut, Moon, Pause, Refrigerator, Sofa,
  Sun, UserX, Utensils, ShowerHead, Heart, Thermometer, Bell, Plug, PlugZap, Microwave, User, Users,
  type LucideIcon,
} from "lucide-react";
import type { ActivityCategory, RiskLevel } from "./types";

const ICONS: Record<string, LucideIcon> = {
  activity: Activity,
  "alert-triangle": AlertTriangle,
  armchair: Armchair,
  bath: Bath,
  bed: Bed,
  "bed-single": Bed,
  coffee: Coffee,
  "cooking-pot": CookingPot,
  "door-open": DoorOpen,
  footprints: Footprints,
  home: Home,
  "lamp-desk": LampDesk,
  "log-in": LogIn,
  "log-out": LogOut,
  moon: Moon,
  pause: Pause,
  refrigerator: Refrigerator,
  sofa: Sofa,
  sun: Sun,
  "user-x": UserX,
  utensils: Utensils,
  "shower-head": ShowerHead,
  heart: Heart,
  thermometer: Thermometer,
  bell: Bell,
  plug: Plug,
  "plug-zap": PlugZap,
  microwave: Microwave,
  user: User,
  users: Users,
};

export function activityIcon(name: string): LucideIcon {
  return ICONS[name] ?? Activity;
}

// Category → tailwind colour tokens. Soft tinted backgrounds, like the mockups.
export const categoryStyle: Record<ActivityCategory, { dot: string; bg: string; fg: string }> = {
  sleep:       { dot: "bg-violet-500",  bg: "bg-violet-50 dark:bg-violet-950/40",  fg: "text-violet-600 dark:text-violet-300" },
  hygiene:     { dot: "bg-sky-500",     bg: "bg-sky-50 dark:bg-sky-950/40",        fg: "text-sky-600 dark:text-sky-300" },
  meal:        { dot: "bg-amber-500",   bg: "bg-amber-50 dark:bg-amber-950/40",    fg: "text-amber-600 dark:text-amber-300" },
  mobility:    { dot: "bg-emerald-500", bg: "bg-emerald-50 dark:bg-emerald-950/40",fg: "text-emerald-600 dark:text-emerald-300" },
  rest:        { dot: "bg-teal-500",    bg: "bg-teal-50 dark:bg-teal-950/40",      fg: "text-teal-600 dark:text-teal-300" },
  exit:        { dot: "bg-orange-500",  bg: "bg-orange-50 dark:bg-orange-950/40",  fg: "text-orange-600 dark:text-orange-300" },
  safety:      { dot: "bg-red-500",     bg: "bg-red-50 dark:bg-red-950/40",        fg: "text-red-600 dark:text-red-300" },
  environment: { dot: "bg-cyan-500",    bg: "bg-cyan-50 dark:bg-cyan-950/40",      fg: "text-cyan-600 dark:text-cyan-300" },
  unknown:     { dot: "bg-neutral-400", bg: "bg-neutral-100 dark:bg-neutral-800",  fg: "text-neutral-600 dark:text-neutral-300" },
};

export const riskStyle: Record<RiskLevel, { label: string; bg: string; fg: string; dot: string }> = {
  ok:        { label: "All good",  bg: "bg-emerald-50 dark:bg-emerald-950/40", fg: "text-emerald-700 dark:text-emerald-300", dot: "bg-emerald-500" },
  attention: { label: "Attention", bg: "bg-amber-50 dark:bg-amber-950/40",     fg: "text-amber-700 dark:text-amber-300",     dot: "bg-amber-500" },
  alert:     { label: "Alert",     bg: "bg-red-50 dark:bg-red-950/40",         fg: "text-red-700 dark:text-red-300",         dot: "bg-red-500" },
};

export const severityColor: Record<string, string> = {
  CRITICAL: "bg-red-500",
  HIGH: "bg-orange-500",
  MEDIUM: "bg-amber-500",
  LOW: "bg-emerald-500",
};
