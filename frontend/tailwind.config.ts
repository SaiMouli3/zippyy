import type { Config } from "tailwindcss";

// `zy` tokens mirror docs/zippyy-design-system.md §2.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        zy: {
          brand: "#D54029",
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
      },
      fontFamily: {
        heading: ["Lato", "sans-serif"],
        body: ["Inter", "sans-serif"],
        accent: ["Manrope", "sans-serif"],
      },
      maxWidth: { zy: "1320px" },
      boxShadow: {
        "zy-menu": "0 24px 56px 0 #A7AEBA29",
        "zy-card": "0 5px 20px rgba(0,0,0,.07)",
      },
      keyframes: {
        float: { "0%,100%": { transform: "translateY(0)" }, "50%": { transform: "translateY(-20px)" } },
        marquee: { from: { transform: "translateX(0)" }, to: { transform: "translateX(-50%)" } },
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
      },
      animation: {
        float: "float 4s ease-in-out infinite",
        marquee: "marquee 30s linear infinite",
        "fade-in": "fade-in .3s ease-in-out",
      },
    },
  },
  plugins: [],
};
export default config;
