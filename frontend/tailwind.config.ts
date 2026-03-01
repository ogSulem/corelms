import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#fff7ed",
          100: "#ffedd5",
          200: "#fed7aa",
          300: "#fdba74",
          400: "#fb923c",
          500: "#fe9900",
          600: "#ea8200",
          700: "#c25f00",
          800: "#9a4a00",
          900: "#7c3d00",
          950: "#451a03",
        },
        brandOrange: {
          50: "#fff7ed",
          100: "#ffedd5",
          200: "#fed7aa",
          300: "#fdba74",
          400: "#fb923c",
          500: "#fe9900",
          600: "#ea8200",
          700: "#c25f00",
          800: "#9a4a00",
          900: "#7c3d00",
          950: "#451a03",
        },
        brandGreen: {
          50: "#f3faf0",
          100: "#def4d4",
          200: "#bfe8ab",
          300: "#97d77a",
          400: "#69c34b",
          500: "#3a9926",
          600: "#2f7d1f",
          700: "#28661b",
          800: "#214f16",
          900: "#1c4214",
          950: "#0c2407",
        },
      },
      boxShadow: {
        glass: "0 1px 0 rgba(255,255,255,0.06) inset, 0 24px 70px rgba(0,0,0,0.55)",
      },
      backdropBlur: {
        glass: "14px",
      },
    },
  },
  plugins: [],
} satisfies Config;
