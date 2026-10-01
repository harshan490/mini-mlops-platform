import { create } from "zustand";
import type { BackgroundPreset, Settings } from "@/lib/types";

const USER_KEY = "mini-mlops.user";
const TOKEN_KEY = "mini-mlops.token";

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}
function write(key: string, value: string | null) {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable (private mode) */
  }
}

export interface Appearance {
  theme: "dark" | "light" | "auto";
  accent: string;
  background: BackgroundPreset;
}

interface UIState {
  user: string;
  setUser: (username: string) => void;
  token: string | null;
  setToken: (token: string | null) => void;
  authRequired: boolean;
  setAuthRequired: (v: boolean) => void;
  paletteOpen: boolean;
  setPaletteOpen: (v: boolean) => void;
  appearance: Appearance;
  setAppearance: (patch: Partial<Appearance>) => void;
  notifications: Settings["notifications"] | null;
  setNotifications: (n: Settings["notifications"]) => void;
}

export const useUI = create<UIState>((set) => ({
  user: read(USER_KEY) || "harshan",
  setUser: (username) => {
    write(USER_KEY, username);
    set({ user: username });
  },
  token: read(TOKEN_KEY),
  setToken: (token) => {
    write(TOKEN_KEY, token);
    set({ token });
  },
  authRequired: false,
  setAuthRequired: (v) => set({ authRequired: v }),
  paletteOpen: false,
  setPaletteOpen: (v) => set({ paletteOpen: v }),
  appearance: { theme: "dark", accent: "#3B82F6", background: "cosmic" },
  setAppearance: (patch) => set((s) => ({ appearance: { ...s.appearance, ...patch } })),
  notifications: null,
  setNotifications: (n) => set({ notifications: n }),
}));

export function hexToTriplet(hex: string): string {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
  return `${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255}`;
}

/** Apply theme + accent to the document (CSS variables). */
export function applyAppearance(a: Appearance) {
  const root = document.documentElement;
  const prefersLight = window.matchMedia?.("(prefers-color-scheme: light)").matches;
  const theme = a.theme === "auto" ? (prefersLight ? "light" : "dark") : a.theme;
  root.dataset.theme = theme;
  root.style.setProperty("--accent", hexToTriplet(a.accent));
}
