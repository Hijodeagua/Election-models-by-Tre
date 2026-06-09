import type { Config } from 'tailwindcss';

// Policy & Peaches design tokens — see design-system/ for the source kit.
const config: Config = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        dem: '#2563eb',
        'dem-wash': '#eff6ff',
        'dem-border': '#dbeafe',
        rep: '#dc2626',
        'rep-wash': '#fdeeee',
        'rep-border': '#f6cccc',
        cream: {
          50: '#faf8f5',
          100: '#f5f0ea',
          200: '#f0ebe5',
          300: '#e8ddd5',
        },
        cocoa: {
          300: '#c9b3a8',
          400: '#a0736a',
          500: '#7c5a52',
          700: '#5c3d2a',
          900: '#2c1810',
        },
        ink: '#2c1810',
        peach: {
          DEFAULT: '#c1533d',
          hover: '#a8442f',
          wash: '#fdf0ed',
          border: '#ecc3b8',
        },
        stamp: {
          DEFAULT: '#4e8c3f',
          wash: '#eef5ea',
        },
      },
      fontFamily: {
        display: ['var(--font-display)', 'Georgia', 'serif'],
        serifbody: ['var(--font-serif-body)', 'Georgia', 'serif'],
      },
    },
  },
  plugins: [],
};

export default config;
