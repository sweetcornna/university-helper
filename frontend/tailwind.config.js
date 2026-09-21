/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Semantic tokens — keep these stable so dark mode just remaps them.
        primary: 'rgb(var(--color-primary) / <alpha-value>)',
        secondary: 'rgb(var(--color-secondary) / <alpha-value>)',
        cta: 'rgb(var(--color-cta) / <alpha-value>)',
        background: 'rgb(var(--color-background) / <alpha-value>)',
        surface: 'rgb(var(--color-surface) / <alpha-value>)',
        'surface-hover': 'rgb(var(--color-surface-hover) / <alpha-value>)',
        text: 'rgb(var(--color-text) / <alpha-value>)',
        'text-muted': 'rgb(var(--color-text-muted) / <alpha-value>)',
        border: 'rgb(var(--color-border) / <alpha-value>)',
        'border-subtle': 'rgb(var(--color-border-subtle) / <alpha-value>)',
        success: 'rgb(var(--color-success) / <alpha-value>)',
        'success-surface': 'rgb(var(--color-success-surface) / <alpha-value>)',
        danger: 'rgb(var(--color-danger) / <alpha-value>)',
        'danger-surface': 'rgb(var(--color-danger-surface) / <alpha-value>)',
        warning: 'rgb(var(--color-warning) / <alpha-value>)',
        'warning-surface': 'rgb(var(--color-warning-surface) / <alpha-value>)',

        // Auth-page palette (apple.com reference). Namespaced under `auth-*`
        // and backed by its own CSS variables so the app's semantic tokens
        // above are left exactly as they are.
        auth: {
          bg: 'rgb(var(--auth-bg) / <alpha-value>)',
          surface: 'rgb(var(--auth-surface) / <alpha-value>)',
          text: 'rgb(var(--auth-text) / <alpha-value>)',
          muted: 'rgb(var(--auth-muted) / <alpha-value>)',
          accent: 'rgb(var(--auth-accent) / <alpha-value>)',
          // Filled-button blue. Stays #0071e3 in dark mode too: the lighter
          // #2997ff accent is a text/link hue and only reaches ~3:1 against
          // white, which would fail AA on a solid button.
          'accent-solid': 'rgb(var(--auth-accent-solid) / <alpha-value>)',
          // Text-on-tint blue/red. The display accent and --color-danger are
          // both too light to sit on their own 10% tints at AA, so the notice
          // and error blocks use these instead.
          'accent-ink': 'rgb(var(--auth-accent-ink) / <alpha-value>)',
          danger: 'rgb(var(--auth-danger) / <alpha-value>)',
          hairline: 'rgb(var(--auth-hairline) / <alpha-value>)',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        // Apple's own faces first so macOS/iOS render SF Pro and — for the
        // Chinese UI — PingFang SC natively. Inter is already loaded and
        // carries everything else.
        display: [
          '-apple-system',
          'BlinkMacSystemFont',
          '"SF Pro Display"',
          '"SF Pro Text"',
          '"PingFang SC"',
          '"Helvetica Neue"',
          'Inter',
          'sans-serif',
        ],
      },
      backdropBlur: {
        glass: '16px',
      },
      animation: {
        'fade-in': 'fadeIn 200ms ease-out',
        // Auth pages. cubic-bezier(0.28, 0.11, 0.32, 1) is Apple's easing.
        'auth-rise': 'authRise 640ms cubic-bezier(0.28, 0.11, 0.32, 1) both',
        'auth-chapter': 'authChapterFill 14s cubic-bezier(0.28, 0.11, 0.32, 1) infinite',
      },
      keyframes: {
        fadeIn: {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        authRise: {
          from: { opacity: '0', transform: 'translateY(12px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        // One ambient "chapter" completing. Only transform + opacity so the
        // whole field stays on the compositor; the tail fades out before the
        // track snaps back to empty, so the reset is never visible.
        authChapterFill: {
          '0%': { transform: 'scaleX(0)', opacity: '0' },
          '6%': { opacity: '1' },
          '52%': { transform: 'scaleX(1)' },
          '78%': { transform: 'scaleX(1)', opacity: '1' },
          '92%': { transform: 'scaleX(1)', opacity: '0' },
          '100%': { transform: 'scaleX(0)', opacity: '0' },
        },
      },
    },
  },
  plugins: [],
}
