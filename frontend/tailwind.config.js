/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: '#832e44',
        secondary: '#5b1724',
        accent: '#f7dfed',
        light: '#fafafa',
        'muted-pink': '#e4b6d0',
        'dark-pink': '#cc8597',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        'pink': '0px 0px 4px 0px rgba(253,171,181,0.2)',
      },
    },
  },
  plugins: [],
}
