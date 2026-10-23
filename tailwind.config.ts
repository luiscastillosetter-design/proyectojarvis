import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}"
  ],
  theme: {
    extend: {
      colors: {
        cyber: {
          bg: "#040711",
          panel: "#0A1022",
          cyan: "#00E5FF",
          blue: "#0066FF",
          purple: "#8B5CF6",
          emerald: "#10B981",
          amber: "#F59E0B",
          danger: "#EF4444"
        }
      },
      animation: {
        "pulse-slow": "pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "spin-slow": "spin 14s linear infinite",
        "spin-reverse": "spin 18s linear infinite reverse"
      }
    }
  },
  plugins: []
};

export default config;