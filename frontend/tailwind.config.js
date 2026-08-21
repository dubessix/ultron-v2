/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ultron: {
          bg: "#0A0A0F",
          textPrimary: "#F5F5F7",
          textSecondary: "#8B8B96",
          blue: "#7DD3FC",
          gold: "#FBBF24",
          border: "rgba(255, 255, 255, 0.08)"
        }
      },
      animation: {
        'breath': 'breath 4s ease-in-out infinite',
      },
      keyframes: {
        breath: {
          '0%, 100%': { transform: 'scale(1)', opacity: 0.85 },
          '50%': { transform: 'scale(1.05)', opacity: 1 },
        }
      }
    },
  },
  plugins: [],
}
