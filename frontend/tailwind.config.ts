import type { Config } from "tailwindcss";

// Tokens mirror docs/zippyy-design-system.md (extracted from zippyy.ai). Brand red, near-black ink and the
// off-white canvas come straight from the website; status tones are restrained and always paired with text.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        zy: {
          brand: "#D54029",
          "brand-hover": "#B9361F",
          "brand-soft": "#FBEDEA",
          ink: "#121212",
          "ink-2": "#1E1E1E",
          "ink-3": "#2E2E2E",
          paper: "#FAFAFA",
          "paper-2": "#F5F5F5",
          muted: "#9E9E9E",
          "muted-warm": "#BAA0A0",
          link: "#0C77FF",
          star: "#FF8C00",
        },
        canvas: "#FAFAFA",
        surface: "#FFFFFF",
        line: { DEFAULT: "#E7E7E7", strong: "#D6D6D6" },
        fg: { DEFAULT: "#2E2E2E", strong: "#121212", muted: "#5F5F5F", subtle: "#8A8A8A" },
        ok: { DEFAULT: "#1F7A4D", soft: "#E8F4EE" },
        warn: { DEFAULT: "#9A5B00", soft: "#FFF4E2" },
        danger: { DEFAULT: "#B42318", soft: "#FDECEA" },
        info: { DEFAULT: "#0B63D1", soft: "#E8F1FF" },
      },
      fontFamily: {
        heading: ["var(--font-lato)", "Lato", "sans-serif"],
        body: ["var(--font-inter)", "Inter", "sans-serif"],
        accent: ["Manrope", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      fontSize: { "2xs": ["11px", "14px"] },
      maxWidth: { zy: "1320px" },
      boxShadow: {
        "zy-menu": "0 24px 56px 0 #A7AEBA29",
        "zy-card": "0 5px 20px rgba(0,0,0,.07)",
        panel: "0 1px 2px rgba(18,18,18,.04)",
        pop: "0 12px 32px rgba(18,18,18,.12)",
      },
      keyframes: {
        float: { "0%,100%": { transform: "translateY(0)" }, "50%": { transform: "translateY(-20px)" } },
        marquee: { from: { transform: "translateX(0)" }, to: { transform: "translateX(-50%)" } },
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        shimmer: { "0%": { backgroundPosition: "-400px 0" }, "100%": { backgroundPosition: "400px 0" } },
        pulse2: { "0%,100%": { opacity: "1" }, "50%": { opacity: ".35" } },
      },
      animation: {
        float: "float 4s ease-in-out infinite",
        marquee: "marquee 30s linear infinite",
        "fade-in": "fade-in .2s ease-out",
        shimmer: "shimmer 1.4s linear infinite",
        pulse2: "pulse2 2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
export default config;
