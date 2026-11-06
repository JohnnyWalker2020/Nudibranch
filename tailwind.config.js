// Builds static/css/tailwind.css. See "Development" in the README for the command.
//
// The pages use Tailwind's cyan, blue and slate classes, and each tank's theme swaps those palettes
// (aquarium/themes.py). So those three are CSS variables here: this file sets the default colours,
// and base.html overrides them for the selected tank.
const colors = require('tailwindcss/colors');
const plugin = require('tailwindcss/plugin');

const THEMED = ['cyan', 'blue', 'slate'];
const channels = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).join(' ');

const themedColors = {};
const defaults = {};
for (const name of THEMED) {
  themedColors[name] = {};
  for (const [step, hex] of Object.entries(colors[name])) {
    themedColors[name][step] = `rgb(var(--${name}-${step}) / <alpha-value>)`;
    defaults[`--${name}-${step}`] = channels(hex);
  }
}

module.exports = {
  darkMode: 'class',
  content: [
    './templates/**/*.html',
    './static/js/*.js',
    './aquarium/*.py',
    '!./aquarium/tests.py',
  ],
  theme: {
    extend: {
      colors: {
        brand: { 50: '#f0fdfa', 500: '#14b8a6', 600: '#0d9488', 900: '#134e4a' },
        ...themedColors,
      },
    },
  },
  plugins: [plugin(({ addBase }) => addBase({ ':root': defaults }))],
};
