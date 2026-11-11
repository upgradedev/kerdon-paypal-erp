/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['selector', 'body:not(.theme-light)'],
  theme: {
    extend: {
      colors: {
        kerdon: {
          bg: 'var(--bg)',
          panel: 'var(--panel)',
          card: 'var(--card)',
          line: 'var(--line)',
          accent: 'var(--accent)',
        },
      },
    },
  },
  plugins: [],
};
