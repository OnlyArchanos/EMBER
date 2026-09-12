/**
 * Sidebar — Filter controls, filtered detection stats, and global operational metrics.
 *
 * Visual separation ensures global counts (persistent_active_count, persistent_ended_count,
 * flagged_open_count) are never confused with filtered detection metrics (total_fires, by_type, by_state).
 */

import { useEffect, useState } from 'react';
import { getStats } from '../api/client.js';
import { colors, fireTypeColor } from '../theme.js';

// Canonical fire_type enum list from docs/data-model.md (excluding internal 'pending')
const CANONICAL_FIRE_TYPES = [
  { value: '', label: 'All Fire Types' },
  { value: 'industrial', label: 'Industrial' },
  { value: 'wildfire', label: 'Wildfire' },
  { value: 'agricultural', label: 'Agricultural' },
  { value: 'unclassified', label: 'Unclassified' },
];

function Sidebar({
  filters = { fire_type: '', state: '', date_from: '', date_to: '' },
  onFilterChange,
  initialStats = null,
}) {
  const [stats, setStats] = useState(initialStats);
  const [availableStates, setAvailableStates] = useState(
    initialStats?.by_state ? Object.keys(initialStats.by_state).filter(Boolean).sort() : []
  );
  const [loading, setLoading] = useState(!initialStats);
  const [error, setError] = useState(null);

  // 1. Fetch unfiltered stats once on mount to discover valid state names if not provided
  useEffect(() => {
    if (initialStats?.by_state) return;

    let cancelled = false;

    async function loadStates() {
      try {
        const unfilteredStats = await getStats({});
        if (!cancelled && unfilteredStats && unfilteredStats.by_state) {
          const states = Object.keys(unfilteredStats.by_state).filter(Boolean).sort();
          setAvailableStates(states);
          setStats((prev) => prev || unfilteredStats);
          setLoading(false);
        }
      } catch (err) {
        console.error('Failed to load initial states list:', err);
      }
    }

    loadStates();
    return () => {
      cancelled = true;
    };
  }, [initialStats]);

  // 2. Re-fetch stats whenever active filters change
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    async function fetchFilteredStats() {
      try {
        const queryParams = {};
        if (filters.fire_type) queryParams.fire_type = filters.fire_type;
        if (filters.state) queryParams.state = filters.state;
        if (filters.date_from) queryParams.date_from = filters.date_from;
        if (filters.date_to) queryParams.date_to = filters.date_to;

        const data = await getStats(queryParams);
        if (!cancelled) {
          setStats(data);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          console.error('Failed to fetch filtered stats:', err);
          setError(err.message);
          setLoading(false);
        }
      }
    }

    fetchFilteredStats();
    return () => {
      cancelled = true;
    };
  }, [filters.fire_type, filters.state, filters.date_from, filters.date_to]);

  // Handle individual filter updates
  function handleParamChange(param, value) {
    if (onFilterChange) {
      onFilterChange({
        ...filters,
        [param]: value,
      });
    }
  }

  // Clear all filters back to defaults
  function handleReset() {
    if (onFilterChange) {
      onFilterChange({
        fire_type: '',
        state: '',
        date_from: '',
        date_to: '',
      });
    }
  }

  const hasActiveFilters = Boolean(
    filters.fire_type || filters.state || filters.date_from || filters.date_to
  );

  return (
    <aside
      className="flex flex-col h-full bg-panel border-r border-border text-text-primary overflow-y-auto"
      style={{ width: '320px', minWidth: '320px', backgroundColor: colors.panel, borderColor: colors.border }}
    >
      {/* Header */}
      <div className="p-4 border-b border-border">
        <div className="flex items-center gap-2">
          <span className="text-xl">🛰️</span>
          <div>
            <h1 className="text-sm font-bold tracking-wide text-text-primary uppercase">
              Thermal Intelligence
            </h1>
            <p className="text-xs text-text-muted">FIRMS & OSM Detection System</p>
          </div>
        </div>
      </div>

      {/* Filter Controls */}
      <div className="p-4 border-b border-border space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-text-muted uppercase tracking-wider">
            Filters
          </span>
          {hasActiveFilters && (
            <button
              onClick={handleReset}
              className="text-xs text-accent hover:underline cursor-pointer"
              style={{ color: colors.accent }}
            >
              Reset All
            </button>
          )}
        </div>

        {/* Fire Type dropdown */}
        <div>
          <label className="block text-xs text-text-muted mb-1">Fire Type</label>
          <select
            value={filters.fire_type || ''}
            onChange={(e) => handleParamChange('fire_type', e.target.value)}
            className="w-full text-xs px-2.5 py-1.5 rounded border border-border bg-background text-text-primary focus:outline-none focus:border-accent"
            style={{ backgroundColor: colors.background, borderColor: colors.border }}
          >
            {CANONICAL_FIRE_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>

        {/* State dropdown */}
        <div>
          <label className="block text-xs text-text-muted mb-1">State / Region</label>
          <select
            value={filters.state || ''}
            onChange={(e) => handleParamChange('state', e.target.value)}
            className="w-full text-xs px-2.5 py-1.5 rounded border border-border bg-background text-text-primary focus:outline-none focus:border-accent"
            style={{ backgroundColor: colors.background, borderColor: colors.border }}
          >
            <option value="">All States</option>
            {availableStates.map((st) => (
              <option key={st} value={st}>
                {st}
              </option>
            ))}
          </select>
        </div>

        {/* Date range pickers */}
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="block text-xs text-text-muted mb-1">Date From</label>
            <input
              type="date"
              value={filters.date_from || ''}
              onChange={(e) => handleParamChange('date_from', e.target.value)}
              className="w-full text-xs px-2 py-1.5 rounded border border-border bg-background text-text-primary focus:outline-none focus:border-accent"
              style={{ backgroundColor: colors.background, borderColor: colors.border }}
            />
          </div>
          <div>
            <label className="block text-xs text-text-muted mb-1">Date To</label>
            <input
              type="date"
              value={filters.date_to || ''}
              onChange={(e) => handleParamChange('date_to', e.target.value)}
              className="w-full text-xs px-2 py-1.5 rounded border border-border bg-background text-text-primary focus:outline-none focus:border-accent"
              style={{ backgroundColor: colors.background, borderColor: colors.border }}
            />
          </div>
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div className="p-4 m-3 rounded bg-red-950/40 border border-red-800 text-xs text-red-200">
          Error loading stats: {error}
        </div>
      )}

      {/* Section 1: Filtered Results */}
      <div className="p-4 border-b border-border space-y-4">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wider text-text-muted">
            Filtered Results
          </span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-background text-text-muted border border-border">
            {hasActiveFilters ? 'Active filters' : 'All detections'}
          </span>
        </div>

        {/* Total Fires */}
        <div
          className="p-3 rounded-lg border border-border flex items-baseline justify-between"
          style={{ backgroundColor: colors.background, borderColor: colors.border }}
        >
          <span className="text-xs text-text-muted">Total Hotspots</span>
          {loading ? (
            <div className="h-6 w-12 bg-border/50 animate-pulse rounded" />
          ) : (
            <span className="text-xl font-bold tracking-tight text-text-primary">
              {(stats?.total_fires ?? 0).toLocaleString()}
            </span>
          )}
        </div>

        {/* By Fire Type */}
        <div className="space-y-2">
          <span className="text-[11px] font-medium text-text-muted">By Fire Type</span>
          {loading ? (
            <div className="space-y-1.5">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="h-5 bg-border/40 animate-pulse rounded" />
              ))}
            </div>
          ) : stats && stats.by_type && Object.keys(stats.by_type).length > 0 ? (
            <div className="space-y-1.5">
              {['industrial', 'wildfire', 'agricultural', 'unclassified'].map((type) => {
                const count = stats.by_type[type] ?? 0;
                const total = stats.total_fires || 1;
                const percent = Math.round((count / total) * 100);
                const color = fireTypeColor[type] || colors.textMuted;

                return (
                  <div key={type} className="text-xs">
                    <div className="flex justify-between items-center mb-0.5">
                      <div className="flex items-center gap-1.5">
                        <span
                          className="w-2 h-2 rounded-full inline-block"
                          style={{ backgroundColor: color }}
                        />
                        <span className="capitalize text-text-primary">{type}</span>
                      </div>
                      <span className="text-text-muted font-mono">{count}</span>
                    </div>
                    {/* Visual proportion bar */}
                    <div className="w-full h-1 rounded bg-background overflow-hidden">
                      <div
                        className="h-full rounded transition-all duration-300"
                        style={{ width: `${percent}%`, backgroundColor: color }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="text-xs text-text-muted py-1 italic">No detections matching filter</div>
          )}
        </div>

        {/* By State */}
        <div className="space-y-1.5">
          <span className="text-[11px] font-medium text-text-muted">By State</span>
          {loading ? (
            <div className="h-5 bg-border/40 animate-pulse rounded" />
          ) : stats && stats.by_state && Object.keys(stats.by_state).length > 0 ? (
            <div className="space-y-1 text-xs">
              {Object.entries(stats.by_state).map(([st, cnt]) => (
                <div key={st} className="flex justify-between items-center text-text-muted">
                  <span className="text-text-primary truncate">{st}</span>
                  <span className="font-mono">{cnt}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-xs text-text-muted py-1 italic">No state data matching filter</div>
          )}
        </div>
      </div>

      {/* Section 2: Operational Status (Global, Deliberately Unfiltered) */}
      <div className="p-4 space-y-3 mt-auto">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wider text-text-muted">
            Current Status
          </span>
          <span
            className="text-[10px] px-1.5 py-0.5 rounded border"
            style={{
              borderColor: colors.border,
              backgroundColor: colors.background,
              color: colors.textMuted,
            }}
          >
            Global Lifetime
          </span>
        </div>

        <div className="grid grid-cols-1 gap-2">
          {/* Flagged Open Count */}
          <div
            className="p-3 rounded-lg border flex items-center justify-between"
            style={{
              backgroundColor: colors.background,
              borderColor: colors.border,
            }}
          >
            <div>
              <div className="text-xs font-medium text-text-primary flex items-center gap-1.5">
                <span style={{ color: colors.accent }}>⚠</span>
                <span>Flagged Open</span>
              </div>
              <p className="text-[10px] text-text-muted">Unexplained persistent sources</p>
            </div>
            {loading && !stats ? (
              <div className="h-6 w-8 bg-border/50 animate-pulse rounded" />
            ) : (
              <span
                className="text-base font-bold font-mono px-2 py-0.5 rounded"
                style={{
                  color: colors.accent,
                  backgroundColor: `${colors.accent}15`,
                }}
              >
                {stats?.flagged_open_count ?? 0}
              </span>
            )}
          </div>

          {/* Persistent Active */}
          <div
            className="p-2.5 rounded-lg border flex items-center justify-between"
            style={{
              backgroundColor: colors.background,
              borderColor: colors.border,
            }}
          >
            <div className="text-xs text-text-primary">
              <span>Persistent Active</span>
              <p className="text-[10px] text-text-muted">Continuously detected clusters</p>
            </div>
            {loading && !stats ? (
              <div className="h-5 w-8 bg-border/50 animate-pulse rounded" />
            ) : (
              <span className="text-sm font-semibold font-mono text-emerald-400">
                {stats?.persistent_active_count ?? 0}
              </span>
            )}
          </div>

          {/* Persistent Ended */}
          <div
            className="p-2.5 rounded-lg border flex items-center justify-between"
            style={{
              backgroundColor: colors.background,
              borderColor: colors.border,
            }}
          >
            <div className="text-xs text-text-primary">
              <span>Persistent Ended</span>
              <p className="text-[10px] text-text-muted">Cooled/inactive historical clusters</p>
            </div>
            {loading && !stats ? (
              <div className="h-5 w-8 bg-border/50 animate-pulse rounded" />
            ) : (
              <span className="text-sm font-semibold font-mono text-text-muted">
                {stats?.persistent_ended_count ?? 0}
              </span>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}

export default Sidebar;
