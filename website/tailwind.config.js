/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'vectordrive': {
          DEFAULT: '#2D761E',
          alt: '#2D7640',
          light: '#3ea82b',
          dark: '#1e5214',
        },
        'sega-blue': {
          DEFAULT: '#184191',
          light: '#2259c7',
          dark: '#0e295e',
        },
        'sollium-red': {
          DEFAULT: '#E41B21',
          light: '#f43f45',
          dark: '#a81318',
        },
        'sollium-dark': {
          DEFAULT: '#0D0E12',
          card: '#14161d',
          surface: '#1a1d27',
          border: '#272b38',
          hover: '#222633',
        }
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      boxShadow: {
        'glow-green': '0 0 25px -5px rgba(45, 118, 30, 0.5)',
        'glow-green-lg': '0 0 45px -5px rgba(45, 118, 30, 0.65)',
        'glow-blue': '0 0 25px -5px rgba(24, 65, 145, 0.5)',
        'glow-blue-lg': '0 0 45px -5px rgba(24, 65, 145, 0.65)',
        'glow-red': '0 0 20px -5px rgba(228, 27, 33, 0.4)',
      },
      animation: {
        'pulse-subtle': 'pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'float': 'float 6s ease-in-out infinite',
      },
      keyframes: {
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-10px)' },
        }
      }
    },
  },
  plugins: [],
}
