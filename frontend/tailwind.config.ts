import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#fff7ed",
          100: "#ffedd5",
          200: "#fed7aa",
          300: "#fdba74",
          400: "#fb923c",
          500: "#f97316",
          600: "#ea580c",
          700: "#c2410c",
          800: "#9a3412",
          900: "#7c2d12",
        },
        // Dark-first semantic surface tokens (Modern Dark / Linear aesthetic).
        // Pages use `background`, cards use `card`, chips/fills use `surface`,
        // borders/dividers use `line`, and text steps through foreground →
        // secondary → muted → faint. Brand stays the FoodAI orange, brightened
        // via brand-300/400 for accent text on dark surfaces.
        background: "#0b0b10",
        card: "#15151c",
        surface: "#1e1e28",
        elevated: "#2a2a35",
        line: "#262630",
        foreground: "#f4f4f5",
        secondary: "#d4d4d8",
        muted: "#a1a1aa",
        faint: "#71717a",
      },
    },
  },
  plugins: [],
};
export default config;
