/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    "./templates/**/*.html",
    "./src/kwuo/**/*.py"
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Onest', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        display: ['"Bricolage Grotesque"', 'sans-serif'],
        heading: ['"Bricolage Grotesque"', 'sans-serif'],
      },
      colors: {
        kwuo: {
          sand: '#F7F4EE',
          sage: '#8A9A86',
          bronze: '#C07D53',
          mahogany: '#2E150F',
          gold: '#D3C18E',
          canvas: '#FAF7F0',
          dark: {
            base: '#15100E',
            surface: '#1E1614',
            subtle: '#1E1612',
            canvas: '#16110F',
            accent: '#2B1F19',
            border: '#332420',
            'border-subtle': 'rgba(61, 45, 35, 0.6)',
            input: '#4D392D',
            heading: '#FAF8F5',
            body: '#C8BEB7',
          }
        },
        theme: {
          base: 'var(--color-bg-base)',
          surface: 'var(--color-bg-surface)',
          canvas: 'var(--color-canvas)',
          'surface-subtle': 'var(--color-surface-subtle)',
          border: 'var(--color-border)',
          'border-subtle': 'var(--color-border-subtle)',
          heading: 'var(--color-text-heading)',
          body: 'var(--color-text-body)',
          muted: 'var(--color-text-muted)',
          interactive: {
            DEFAULT: 'var(--color-interactive)',
            hover: 'var(--color-interactive-hover)',
            text: 'var(--color-interactive-text)',
          }
        }
      }
    }
  },
  plugins: [
    require('@tailwindcss/forms'),
    require('@tailwindcss/typography'),
  ],
};
