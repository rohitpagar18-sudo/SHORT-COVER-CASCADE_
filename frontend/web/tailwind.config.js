/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      // Theme palette resolves through CSS variables — see index.css.
      // Tailwind classes like `bg-surface`, `text-ink`, `border-line`,
      // `bg-card`, `text-muted` swap automatically when the `.dark`
      // class is on <html>.
      colors: {
        sidebar: "#0B1220",
        bg: "var(--c-bg)",
        surface: "var(--c-surface)",
        card: "var(--c-card)",
        ink: "var(--c-ink)",
        muted: "var(--c-muted)",
        line: "var(--c-line)",
        line2: "var(--c-line2)",
        accent: "var(--c-accent)",
        ok: "#16A34A",
        warn: "#D97706",
        bad: "#DC2626",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "Segoe UI", "Roboto", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(15, 23, 42, 0.04), 0 1px 1px rgba(15, 23, 42, 0.06)",
      },
    },
  },
  plugins: [],
};
