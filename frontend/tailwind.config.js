/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        clinical: {
          dark: '#0f172a',
          surface: '#1e293b',
          border: '#334155',
          text: '#f8fafc',
          muted: '#94a3b8',
          red: '#dc2626',
          redDark: '#991b1b',
          blue: '#2563eb',
          orange: '#ea580c',
          green: '#16a34a'
        }
      },
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
        sans: ['system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      animation: {
        'alarm-flash': 'alarmFlash 1s infinite alternate ease-in-out',
        'pulse-subtle': 'subtlePulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
      keyframes: {
        alarmFlash: {
          '0%': { backgroundColor: 'rgba(220, 38, 38, 0.95)' },
          '100%': { backgroundColor: 'rgba(153, 27, 27, 0.98)' },
        },
        subtlePulse: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.6' },
        }
      }
    },
  },
  plugins: [],
}
