import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        strong: "var(--color-strong)",
        partial: "var(--color-partial)",
        weak: "var(--color-weak)",
        primary: "var(--color-primary)",
        ink: "var(--color-ink)",
        muted: "var(--color-muted)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
