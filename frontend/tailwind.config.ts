import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0b0e17",
        card: "#141824",
        border: "#1e2435",
        green: { signal: "#16c784" },
        red: { signal: "#ea3943" },
        amber: { signal: "#f59e0b" },
      },
    },
  },
  plugins: [],
};
export default config;
