/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        orbitron: ['Orbitron', 'sans-serif'],
      },
      colors: {
        cyan: {
          400: '#00f5ff',
          500: '#00d1da',
        },
        purple: {
          400: '#b026ff',
          600: '#8b1fd6',
        },
      },
    },
  },
  plugins: [],
}
