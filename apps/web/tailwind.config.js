/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  // Touch screens keep :hover after a tap; only apply hover styles where a mouse can hover.
  future: {
    hoverOnlyWhenSupported: true
  },
  theme: {
    extend: {
      colors: {
        primary: "#0ddbf2",
        accept: "#00FF66",
        answer: "#16a750",
        reject: "#FF0055",
        "background-light": "#f5f8f8",
        "background-dark": "#050507",
        surface: "rgba(20, 22, 28, 0.65)"
      },
      fontFamily: {
        display: ["Space Grotesk", "sans-serif"],
        body: ["Plus Jakarta Sans", "sans-serif"]
      },
      borderRadius: {
        DEFAULT: "1.5rem",
        lg: "1.5rem",
        xl: "1.5rem",
        full: "9999px"
      },
      boxShadow: {
        "neon-primary": "0 0 20px rgba(13, 219, 242, 0.4)",
        "neon-accept": "0 0 20px rgba(0, 255, 102, 0.4)",
        "neon-answer": "0 0 20px rgba(11, 116, 53, 0.69)",
        "neon-reject": "0 0 20px rgba(255, 0, 85, 0.4)"
      }
    }
  }
};
