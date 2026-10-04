/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      colors: {
        ink: {
          950: '#05080f',
          900: '#0a0f1c',
          850: '#0d1424',
          800: '#111a2e',
          700: '#1a253d',
          600: '#26344f',
        },
        brand: {
          300: '#7ee7f7',
          400: '#38d5f0',
          500: '#14b8d6',
          600: '#0e93b0',
        },
      },
      boxShadow: {
        glow: '0 0 0 1px rgba(56,213,240,.25), 0 8px 40px -12px rgba(56,213,240,.35)',
        card: '0 1px 0 0 rgba(255,255,255,.04) inset, 0 20px 40px -24px rgba(0,0,0,.6)',
      },
      keyframes: {
        'fade-up': { from: { opacity: 0, transform: 'translateY(6px)' }, to: { opacity: 1, transform: 'none' } },
        pulseRing: { '0%': { transform: 'scale(.9)', opacity: .7 }, '100%': { transform: 'scale(2.2)', opacity: 0 } },
        shimmer: { '0%': { transform: 'translateX(-100%)' }, '100%': { transform: 'translateX(300%)' } },
        'score-bump': {
          '0%': { opacity: 0, transform: 'translateY(8px) scale(.85)' },
          '15%': { opacity: 1, transform: 'translateY(0) scale(1.08)' },
          '30%': { transform: 'translateY(0) scale(1)' },
          '80%': { opacity: 1, transform: 'translateY(-2px)' },
          '100%': { opacity: 0, transform: 'translateY(-14px)' },
        },
        'glow-pulse': {
          '0%': { boxShadow: '0 0 0 0 rgba(52,211,153,.45)' },
          '100%': { boxShadow: '0 0 0 18px rgba(52,211,153,0)' },
        },
      },
      animation: {
        'fade-up': 'fade-up .35s ease-out both',
        'pulse-ring': 'pulseRing 1.8s ease-out infinite',
        shimmer: 'shimmer 1.2s ease-in-out infinite',
        'score-bump': 'score-bump 3s ease-out both',
        'glow-pulse': 'glow-pulse 1.1s ease-out 2',
      },
    },
  },
  plugins: [],
};
