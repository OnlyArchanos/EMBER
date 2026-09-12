/**
 * Design tokens — single source of truth for all colors in the app.
 * Every other file imports from here; no hex values are defined elsewhere.
 * main.jsx applies these as CSS custom properties on document.documentElement
 * so Tailwind utility classes can reference them via var().
 */

export const colors = {
  background:    '#0a0a0f',
  panel:         '#161b22',
  border:        '#2a2e37',
  textPrimary:   '#e6e6e6',
  textMuted:     '#8b949e',
  accent:        '#ff6b35',
  danger:        '#f85149',

  fireIndustrial:   '#4a90d9',
  fireWildfire:     '#e5484d',
  fireAgricultural: '#5fb85c',
  fireUnclassified: '#9b8cf2',

  statusReviewed:   '#58a6ff',
};

/**
 * Map a fire_type value from the API to its display color.
 * Keys match the snake_case values returned by the backend exactly.
 */
export const fireTypeColor = {
  industrial:   colors.fireIndustrial,
  wildfire:     colors.fireWildfire,
  agricultural: colors.fireAgricultural,
  unclassified: colors.fireUnclassified,
};
