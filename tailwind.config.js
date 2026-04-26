/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './webapp/templates/**/*.html',
    './webapp/templates/**/*.j2',
    './webapp/static/**/*.html',
  ],
  theme: {
    extend: {
      colors: {
        'soil-50': '#f5f3ec',
        'soil-100': '#e8e2d2',
        'soil-200': '#cdc2a3',
        'soil-700': '#5a4f3a',
        'soil-800': '#3a3225',
        'soil-900': '#1f1b14',
        'forest-300': '#86efac',
        'forest-400': '#4ade80',
        'forest-500': '#16a34a',
        'forest-600': '#15803d',
        'forest-700': '#166534',
        'forest-800': '#14532d',
        'forest-900': '#0a3a1f',
        'bg-base': '#0a0f0d',
        'bg-card': '#11181f',
        'bg-elev': '#1a232c',
        'border-subtle': '#1e2d33',
        'border-default': '#2a3a40',
        'text-primary': '#e8eef0',
        'text-secondary': '#9bb0b8',
        'text-muted': '#6a8088',
        'amber-warm': '#e0a458',
      },
      fontFamily: {
        'sans': ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        'serif': ['Fraunces', 'Georgia', 'serif'],
      }
    }
  },
  plugins: [],
}
