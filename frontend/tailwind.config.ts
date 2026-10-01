import type { Config } from "tailwindcss";

const v = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg0: v("bg-0"),
        bg1: v("bg-1"),
        glass: v("glass"),
        line: v("line"),
        ink: v("ink"),
        muted: v("muted"),
        accent: v("accent"),
        m: {
          blue: v("m-blue"),
          violet: v("m-violet"),
          cyan: v("m-cyan"),
          emerald: v("m-emerald"),
          amber: v("m-amber"),
          pink: v("m-pink"),
          red: v("m-red"),
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["JetBrains Mono", "Cascadia Code", "Consolas", "monospace"],
      },
      boxShadow: {
        glass: "inset 0 1px 0 rgba(255,255,255,0.06), 0 0 30px rgba(60,110,255,0.15)",
        glow: "0 0 22px rgb(var(--accent) / 0.45)",
      },
      keyframes: {
        shimmer: { "0%": { backgroundPosition: "-400px 0" }, "100%": { backgroundPosition: "400px 0" } },
        spinSlow: { to: { transform: "rotate(360deg)" } },
        pulseDot: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.35" } },
      },
      animation: {
        shimmer: "shimmer 1.4s linear infinite",
        "spin-slow": "spinSlow 1.2s linear infinite",
        "pulse-dot": "pulseDot 1.6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
