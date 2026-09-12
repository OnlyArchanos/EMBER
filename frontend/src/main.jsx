import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { colors } from './theme.js';
import './index.css';
import App from './App.jsx';

/**
 * Apply theme.js colors as CSS custom properties on <html> so that
 * index.css's @theme block (and any var() reference) can use them.
 * This keeps theme.js as the single file containing hex values.
 */
const cssVarMap = {
  '--theme-background':       colors.background,
  '--theme-panel':            colors.panel,
  '--theme-border':           colors.border,
  '--theme-text-primary':     colors.textPrimary,
  '--theme-text-muted':       colors.textMuted,
  '--theme-accent':           colors.accent,
  '--theme-danger':           colors.danger,
  '--theme-fire-industrial':   colors.fireIndustrial,
  '--theme-fire-wildfire':     colors.fireWildfire,
  '--theme-fire-agricultural': colors.fireAgricultural,
  '--theme-fire-unclassified': colors.fireUnclassified,
  '--theme-status-reviewed':   colors.statusReviewed,
};

for (const [prop, value] of Object.entries(cssVarMap)) {
  document.documentElement.style.setProperty(prop, value);
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
