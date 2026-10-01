import type { BackgroundPreset } from "@/lib/types";

export interface Preset {
  label: string;
  skyTop: string;
  skyMid: string;
  horizon: string;
  glowA: string;
  glowB: string;
  planetBody: string;
  planetRim: string;
  ridges: [string, string, string, string];
  rim: string;
  lake: string;
}

export const BACKGROUNDS: Record<BackgroundPreset, Preset> = {
  cosmic: {
    label: "Cosmic",
    skyTop: "#02040f",
    skyMid: "#0a1238",
    horizon: "#2c2470",
    glowA: "#6d55ff",
    glowB: "#ff7a5c",
    planetBody: "#3b2f8f",
    planetRim: "#a9b8ff",
    ridges: ["#262e6b", "#1a2058", "#111640", "#070a22"],
    rim: "#7f95ff",
    lake: "#090d2a",
  },
  violet: {
    label: "Violet Dusk",
    skyTop: "#08030f",
    skyMid: "#250c3d",
    horizon: "#5c1f6e",
    glowA: "#d75cff",
    glowB: "#ff9a6b",
    planetBody: "#6a2a8a",
    planetRim: "#ffb8f4",
    ridges: ["#3d2060", "#2c1650", "#1d0e3a", "#0d0620"],
    rim: "#e38cff",
    lake: "#14081f",
  },
  aurora: {
    label: "Aurora",
    skyTop: "#01070b",
    skyMid: "#04222c",
    horizon: "#0b4a46",
    glowA: "#2ee6a6",
    glowB: "#22d3ee",
    planetBody: "#0f4c55",
    planetRim: "#8ffff0",
    ridges: ["#123c46", "#0d2f39", "#08202a", "#030f16"],
    rim: "#45f7cf",
    lake: "#03141a",
  },
  eclipse: {
    label: "Eclipse",
    skyTop: "#000002",
    skyMid: "#05060e",
    horizon: "#151830",
    glowA: "#8a9dff",
    glowB: "#d9def5",
    planetBody: "#0a0b14",
    planetRim: "#f4f6ff",
    ridges: ["#1b1e33", "#13152a", "#0c0e1d", "#050610"],
    rim: "#c8d2ff",
    lake: "#05060d",
  },
  nebula: {
    label: "Nebula",
    skyTop: "#040218",
    skyMid: "#160b45",
    horizon: "#3d2496",
    glowA: "#8b5cf6",
    glowB: "#3b82f6",
    planetBody: "#4b3aa8",
    planetRim: "#bdb2ff",
    ridges: ["#2e2475", "#221b60", "#161146", "#0a0826"],
    rim: "#a597ff",
    lake: "#0c0826",
  },
};

export function previewGradient(p: Preset): string {
  return `radial-gradient(60% 50% at 75% 18%, ${p.planetRim}55 0%, transparent 60%),
    linear-gradient(180deg, ${p.skyTop} 0%, ${p.skyMid} 40%, ${p.horizon} 58%, ${p.ridges[1]} 60%, ${p.ridges[3]} 100%)`;
}
