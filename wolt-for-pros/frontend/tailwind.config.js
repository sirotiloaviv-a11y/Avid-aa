/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./app/**/*.{js,jsx}', './components/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eef8ff',
          100: '#d8eeff',
          200: '#b9e1ff',
          300: '#89cfff',
          400: '#52b3ff',
          500: '#2a91ff',
          600: '#1372f5',
          700: '#0c5be1',
          800: '#114ab6',
          900: '#14418f',
        },
      },
      boxShadow: {
        card: '0 1px 2px rgba(15, 23, 42, 0.04), 0 4px 16px rgba(15, 23, 42, 0.06)',
      },
    },
  },
  plugins: [],
};
