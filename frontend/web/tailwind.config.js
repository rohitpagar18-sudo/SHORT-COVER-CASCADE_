/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Sidebar / shell are deep slate; cards live on near-white.
        bg: "#0F172A",
        sidebar: "#0B1220",
        card: "#FFFFFF",
        ink: "#0F172A",
        muted: "#64748B",
        ok: "#16A34A",
        warn: "#D97706",
        bad: "#DC2626",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "Segoe UI", "Roboto", "sans-serif"],
      },
    },
  },
  plugins: [],
};
