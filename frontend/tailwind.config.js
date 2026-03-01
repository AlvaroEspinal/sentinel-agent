/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        parcl: {
          bg:             "var(--color-bg)",
          surface:        "var(--color-surface)",
          panel:          "var(--color-panel)",
          border:         "var(--color-border)",
          "border-bright":"var(--color-border-bright)",
          accent:         "var(--color-accent)",
          "accent-dim":   "var(--color-accent-dim)",
          "accent-light": "var(--color-accent-light)",
          text:           "var(--color-text)",
          "text-dim":     "var(--color-text-dim)",
          "text-muted":   "var(--color-text-muted)",
          green:    "#4ade80",
          "green-dim": "#166534",
          red:      "#ef4444",
          "red-dim": "#991b1b",
          amber:    "#fbbf24",
          "amber-dim": "#92400e",
          blue:     "#2563eb",
          "blue-dim": "#1d4ed8",
          "blue-light": "#60a5fa",
        },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', "Fira Code", "Consolas", "monospace"],
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "pulse-fast": "pulse 1s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        scanline: "scanline 8s linear infinite",
        flicker: "flicker 0.15s infinite",
        "fade-in": "fadeIn 0.3s ease-out",
        "slide-in-left": "slideInLeft 0.3s ease-out",
        "slide-in-right": "slideInRight 0.3s ease-out",
        "slide-up": "slideUp 0.3s ease-out",
        glow: "glow 2s ease-in-out infinite alternate",
      },
      keyframes: {
        scanline: {
          "0%": { transform: "translateY(-100%)" },
          "100%": { transform: "translateY(100%)" },
        },
        flicker: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.97" },
        },
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideInLeft: {
          "0%": { transform: "translateX(-20px)", opacity: "0" },
          "100%": { transform: "translateX(0)", opacity: "1" },
        },
        slideInRight: {
          "0%": { transform: "translateX(20px)", opacity: "0" },
          "100%": { transform: "translateX(0)", opacity: "1" },
        },
        slideUp: {
          "0%": { transform: "translateY(10px)", opacity: "0" },
          "100%": { transform: "translateY(0)", opacity: "1" },
        },
        glow: {
          "0%": { boxShadow: "0 0 5px rgba(37, 99, 235, 0.2)" },
          "100%": { boxShadow: "0 0 20px rgba(37, 99, 235, 0.4)" },
        },
      },
      backdropBlur: {
        xs: "2px",
      },
      boxShadow: {
        tactical:
          "0 0 0 1px rgba(37, 99, 235, 0.1), 0 4px 20px rgba(0, 0, 0, 0.5)",
        "tactical-lg":
          "0 0 0 1px rgba(37, 99, 235, 0.15), 0 8px 40px rgba(0, 0, 0, 0.6)",
        "glow-blue": "0 0 15px rgba(37, 99, 235, 0.3)",
        "glow-red": "0 0 15px rgba(239, 68, 68, 0.3)",
        "glow-amber": "0 0 15px rgba(251, 191, 36, 0.3)",
        "glow-green": "0 0 15px rgba(74, 222, 128, 0.3)",
      },
    },
  },
  plugins: [],
};
