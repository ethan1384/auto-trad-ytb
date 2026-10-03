import type { Config } from "tailwindcss";

export default {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: "rgb(11 11 16 / <alpha-value>)",
        raised: "rgb(21 21 29 / <alpha-value>)",
        sunken: "rgb(8 8 12 / <alpha-value>)",
        ink: "rgb(245 244 250 / <alpha-value>)",
        muted: "rgb(166 163 180 / <alpha-value>)",
        faint: "rgb(113 111 130 / <alpha-value>)",
        line: "rgb(255 255 255 / 0.08)",
        "line-strong": "rgb(255 255 255 / 0.16)",
        accent: "rgb(245 176 76 / <alpha-value>)",
        "accent-ink": "rgb(32 21 6 / <alpha-value>)",
        violet: "rgb(167 139 250 / <alpha-value>)",
        ok: "rgb(110 210 160 / <alpha-value>)",
        bad: "rgb(240 133 122 / <alpha-value>)",
        background: "rgb(11 11 16 / <alpha-value>)",
        foreground: "rgb(245 244 250 / <alpha-value>)",
      },
      fontFamily: {
        sans: ["var(--font-geist-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-geist-mono)", "ui-monospace", "monospace"],
      },
      boxShadow: {
        card: "0 12px 40px -12px rgb(0 0 0 / 0.5)",
        glow: "0 4px 24px -4px rgb(245 176 76 / 0.35)",
        lift: "0 20px 50px -16px rgb(0 0 0 / 0.6)",
      },
      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(10px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.5s cubic-bezier(0.22, 1, 0.36, 1) both",
        shimmer: "shimmer 2.5s linear infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
