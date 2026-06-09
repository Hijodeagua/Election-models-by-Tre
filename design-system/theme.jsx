/* Election Oracle Color Tokens */

:root {
  /* Democratic blue */
  --color-dem: #2563eb;
  --color-dem-light: #3b82f6;
  --color-dem-lighter: #60a5fa;
  --color-dem-dark: #1d4ed8;
  --color-dem-darker: #1e40af;

  /* Republican red */
  --color-rep: #dc2626;
  --color-rep-light: #ef4444;
  --color-rep-lighter: #f87171;
  --color-rep-dark: #b91c1c;
  --color-rep-darker: #7f1d1d;

  /* Warm “Policy & Peaches” brand palette */
  --color-peach-50: #fdf0ed;   /* tint / hover wash */
  --color-peach-100: #fbe0d9;  /* soft fill */
  --color-peach-300: #ec9b86;  /* light accent */
  --color-peach-500: #c1533d;  /* primary accent (stamp coral) */
  --color-peach-600: #a8442f;  /* accent hover/press */
  --color-peach-700: #8a3826; /* deep accent */

  /* Warm paper + ink neutrals */
  --color-cream-50: #faf8f5;   /* app background */
  --color-cream-100: #f5f0ea;  /* sunken panel */
  --color-cream-200: #f0ebe5;  /* metadata strip */
  --color-cream-300: #e8ddd5;  /* hairline border */
  --color-cocoa-300: #c9b3a8;  /* faint text */
  --color-cocoa-400: #a0736a;  /* muted text / labels */
  --color-cocoa-500: #7c5a52;  /* secondary text */
  --color-cocoa-700: #5c3d2a;  /* strong text */
  --color-cocoa-900: #2c1810;  /* display ink */

  /* Stamp green (accent for verified/featured) */
  --color-stamp-green: #4e8c3f;

  /* Neutral slate palette */
  --color-slate-50: #f8fafc;
  --color-slate-100: #f1f5f9;
  --color-slate-200: #e2e8f0;
  --color-slate-300: #cbd5e1;
  --color-slate-400: #94a3b8;
  --color-slate-500: #64748b;
  --color-slate-600: #475569;
  --color-slate-700: #334155;
  --color-slate-800: #1e293b;
  --color-slate-900: #0f172a;

  /* Semantic colors */
  --color-bg-primary: var(--color-cream-50);
  --color-bg-secondary: var(--color-cream-100);
  --color-bg-surface: white;
  --color-bg-sunken: var(--color-cream-200);
  --color-bg-overlay: rgba(44, 24, 16, 0.45);

  --color-text-primary: var(--color-cocoa-900);
  --color-text-secondary: var(--color-cocoa-500);
  --color-text-tertiary: var(--color-cocoa-400);
  --color-text-inverse: white;

  --color-border-light: var(--color-cream-300);
  --color-border-default: var(--color-cream-300);
  --color-border-dark: var(--color-cocoa-300);

  /* Accent (peach/coral) semantic aliases */
  --color-accent: var(--color-peach-500);
  --color-accent-hover: var(--color-peach-600);
  --color-accent-wash: var(--color-peach-50);
  --color-accent-border: var(--color-peach-300);

  --color-status-approve: var(--color-dem);
  --color-status-disapprove: var(--color-rep);
  --color-status-neutral: var(--color-slate-500);
  --color-status-loading: var(--color-slate-300);

  /* Interactive colors */
  --color-interactive-hover: var(--color-slate-100);
  --color-interactive-active: var(--color-slate-200);
  --color-interactive-focus: var(--color-dem);

  /* Chart/visualization colors */
  --color-chart-dem: var(--color-dem);
  --color-chart-rep: var(--color-rep);
  --color-chart-neutral: var(--color-slate-400);
  --color-chart-ci-dem: rgba(37, 99, 235, 0.15);
  --color-chart-ci-rep: rgba(220, 38, 38, 0.15);
}
