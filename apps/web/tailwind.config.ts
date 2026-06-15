import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        bg: { 0: "var(--bg-0)", 1: "var(--bg-1)" },
        ink: { DEFAULT: "var(--text)", 2: "var(--text-2)", 3: "var(--text-3)" },
        tint: "var(--tint)",
        success: "var(--green)",
        warning: "var(--amber)",
        danger: "var(--red)",
        intake: "var(--purple)",
      },
      borderRadius: {
        sm: "var(--radius-sm)",
        DEFAULT: "var(--radius)",
        lg: "var(--radius-lg)",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
export default config;
