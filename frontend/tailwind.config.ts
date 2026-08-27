import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './hooks/**/*.{ts,tsx}',
    './lib/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        border: 'hsl(220 13% 91%)',
        muted: 'hsl(220 14% 96%)',
        'muted-foreground': 'hsl(220 9% 46%)',
        primary: 'hsl(222 47% 11%)',
        'primary-foreground': 'hsl(210 40% 98%)',
        accent: 'hsl(220 14% 96%)',
        'accent-foreground': 'hsl(222 47% 11%)',
      },
    },
  },
  plugins: [],
};

export default config;
