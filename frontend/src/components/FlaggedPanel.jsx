/**
 * FlaggedPanel — Displays and details Unexplained Persistent Sources.
 *
 * Surfacing anomalies sorted by anomaly_score descending.
 * Clicking a case fetches detail from GET /api/flags/{id} and calls
 * onFlagSelect with the backend's persistent_source centroid coordinates.
 * Read-only interface for prototype (no PATCH).
 */

import { useEffect, useMemo, useState } from 'react';
import { getFlag } from '../api/client.js';
import { colors } from '../theme.js';

/** Formats an anomaly score float (e.g. 0.6187 -> 61.9%) */
function formatAnomalyScore(score) {
  if (score === null || score === undefined || isNaN(score)) return 'N/A';
  return `${(score * 100).toFixed(1)}%`;
}

/** Formats meters into human-readable distance (km or m) */
function formatDistance(meters) {
  if (meters === null || meters === undefined || isNaN(meters)) return 'Unknown';
  if (meters >= 1000) {
    return `${(meters / 1000).toFixed(1)} km`;
  }
  return `${Math.round(meters)} m`;
}

/** Capitalizes string safely */
function capitalize(str) {
  if (!str) return 'None';
  return str.charAt(0).toUpperCase() + str.slice(1);
}

/** Returns styling tokens for all three canonical statuses */
function getStatusStyle(status) {
  switch (status) {
    case 'open':
      return {
        color: colors.accent,
        backgroundColor: `${colors.accent}18`,
        borderColor: `${colors.accent}40`,
        label: 'Open',
      };
    case 'reviewed':
      return {
        color: colors.statusReviewed,
        backgroundColor: `${colors.statusReviewed}18`,
        borderColor: `${colors.statusReviewed}40`,
        label: 'Reviewed',
      };
    case 'dismissed':
      return {
        color: colors.textMuted,
        backgroundColor: `${colors.textMuted}18`,
        borderColor: `${colors.textMuted}40`,
        label: 'Dismissed',
      };
    default:
      return {
        color: colors.textMuted,
        backgroundColor: 'transparent',
        borderColor: colors.border,
        label: status || 'Unknown',
      };
  }
}

function FlaggedPanel({ flags = [], onFlagSelect, selectedFlagId = null }) {
  // Sort descending: most anomalous case first
  const sortedFlags = useMemo(() => {
    return (Array.isArray(flags) ? [...flags] : []).sort(
      (a, b) => (b.anomaly_score ?? 0) - (a.anomaly_score ?? 0)
    );
  }, [flags]);

  // Selected flag details
  const [activeFlagId, setActiveFlagId] = useState(selectedFlagId);
  const [flagDetail, setFlagDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState(null);

  // Sync external selectedFlagId prop if provided
  useEffect(() => {
    if (selectedFlagId !== undefined && selectedFlagId !== null) {
      setActiveFlagId(selectedFlagId);
    }
  }, [selectedFlagId]);

  // 2. Fetch detail when activeFlagId changes
  useEffect(() => {
    if (!activeFlagId) {
      setFlagDetail(null);
      return;
    }

    let cancelled = false;
    setDetailLoading(true);
    setDetailError(null);

    async function loadDetail() {
      try {
        const detail = await getFlag(activeFlagId);
        if (!cancelled) {
          setFlagDetail(detail);
          setDetailLoading(false);

          // Invoke onFlagSelect with centroid coordinates directly from persistent_source
          if (onFlagSelect && detail) {
            const latitude = detail.persistent_source?.centroid_latitude ?? null;
            const longitude = detail.persistent_source?.centroid_longitude ?? null;
            const clusterId = detail.persistent_source?.cluster_id ?? null;

            onFlagSelect({
              flagId: detail.id,
              clusterId,
              latitude,
              longitude,
              flag: detail,
            });
          }
        }
      } catch (err) {
        if (!cancelled) {
          console.error(`Failed to load detail for flag #${activeFlagId}:`, err);
          setDetailError(err.message);
          setDetailLoading(false);
        }
      }
    }

    loadDetail();
    return () => {
      cancelled = true;
    };
  }, [activeFlagId]);

  function handleSelectFlag(id) {
    if (activeFlagId === id) {
      // Toggle off detail view if already open
      setActiveFlagId(null);
      setFlagDetail(null);
    } else {
      setActiveFlagId(id);
    }
  }

  return (
    <div
      className="flex flex-col h-full bg-panel border-l border-border text-text-primary overflow-hidden"
      style={{
        width: '360px',
        minWidth: '360px',
        backgroundColor: colors.panel,
        borderColor: colors.border,
      }}
    >
      {/* Header */}
      <div className="p-4 border-b border-border flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-base" style={{ color: colors.accent }}>
              ⚠
            </span>
            <h2 className="text-sm font-bold text-text-primary uppercase tracking-wide">
              Flagged Anomalies
            </h2>
          </div>
          <p className="text-xs text-text-muted mt-0.5">
            Unexplained persistent heat sources
          </p>
        </div>
        <span
          className="text-xs font-mono font-semibold px-2 py-0.5 rounded-full border"
          style={{
            borderColor: colors.border,
            backgroundColor: colors.background,
            color: flags.length > 0 ? colors.accent : colors.textMuted,
          }}
        >
          {flags.length}
        </span>
      </div>

      {/* Main Container: List + Optional Detail View */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {/* Zero Case State — Reassuring Monitoring Message */}
        {sortedFlags.length === 0 && (
          <div
            className="p-6 text-center rounded-lg border border-border my-6 space-y-2"
            style={{ backgroundColor: colors.background }}
          >
            <div className="text-3xl">🛡️</div>
            <h3 className="text-sm font-semibold text-text-primary">
              No Anomalies Detected
            </h3>
            <p className="text-xs text-text-muted leading-relaxed">
              All active persistent thermal clusters are matched with verified industrial zones.
              Continuous surveillance active.
            </p>
          </div>
        )}

        {/* Flags List */}
        {sortedFlags.map((flag) => {
            const isSelected = flag.id === activeFlagId;
            const statusStyle = getStatusStyle(flag.status);
            const days = flag.persistent_source?.days_active ?? 0;
            const detections = flag.persistent_source?.member_count ?? 0;

            return (
              <div
                key={flag.id}
                onClick={() => handleSelectFlag(flag.id)}
                className={`p-3 rounded-lg border transition-all cursor-pointer select-none ${
                  isSelected ? 'ring-1' : 'hover:border-text-muted/50'
                }`}
                style={{
                  backgroundColor: colors.background,
                  borderColor: isSelected ? colors.accent : colors.border,
                  boxShadow: isSelected ? `0 0 12px ${colors.accent}20` : 'none',
                }}
              >
                {/* Header row: ID & Status Badge */}
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-bold text-text-primary">
                      Case #{flag.id}
                    </span>
                    <span className="text-[10px] text-text-muted">
                      Cluster {flag.persistent_source?.cluster_id ?? flag.persistent_source_id}
                    </span>
                  </div>

                  <span
                    className="text-[10px] font-medium px-2 py-0.5 rounded border"
                    style={{
                      color: statusStyle.color,
                      backgroundColor: statusStyle.backgroundColor,
                      borderColor: statusStyle.borderColor,
                    }}
                  >
                    {statusStyle.label}
                  </span>
                </div>

                {/* Score & Zone summary */}
                <div className="flex items-baseline justify-between mb-2">
                  <span className="text-xs text-text-muted">
                    Anomaly Confidence
                  </span>
                  <span
                    className="text-sm font-bold font-mono"
                    style={{ color: colors.accent }}
                  >
                    {formatAnomalyScore(flag.anomaly_score)}
                  </span>
                </div>

                {/* Meta details */}
                <div className="text-[11px] text-text-muted space-y-0.5 pt-1.5 border-t border-border/60">
                  <div className="flex justify-between">
                    <span>Nearest Zone:</span>
                    <span className="text-text-primary capitalize">
                      {flag.nearest_zone_type
                        ? `${capitalize(flag.nearest_zone_type)} (${formatDistance(
                            flag.nearest_zone_distance_m
                          )})`
                        : 'None'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Activity:</span>
                    <span className="text-text-primary">
                      {days} days ({detections} hits)
                    </span>
                  </div>
                </div>

                {/* Expanded Detail View (if active) */}
                {isSelected && (
                  <div className="mt-3 pt-3 border-t border-border space-y-2.5 text-xs animate-fadeIn">
                    {detailLoading && (
                      <div className="text-xs text-text-muted italic py-2 text-center">
                        Loading cluster records...
                      </div>
                    )}

                    {detailError && (
                      <div className="text-xs text-red-400 py-1">
                        Failed to load detail: {detailError}
                      </div>
                    )}

                    {flagDetail && !detailLoading && (
                      <>
                        <div className="space-y-1.5 bg-panel/60 p-2.5 rounded border border-border">
                          <div className="font-semibold text-text-primary text-[11px] uppercase tracking-wider mb-1">
                            Persistent Source Details
                          </div>
                          <div className="flex justify-between text-text-muted">
                            <span>Centroid Coordinates:</span>
                            <span className="font-mono text-text-primary">
                              {flagDetail.persistent_source?.centroid_latitude != null &&
                              flagDetail.persistent_source?.centroid_longitude != null
                                ? `${flagDetail.persistent_source.centroid_latitude.toFixed(4)}, ${flagDetail.persistent_source.centroid_longitude.toFixed(4)}`
                                : 'Coordinates unassigned'}
                            </span>
                          </div>
                          <div className="flex justify-between text-text-muted">
                            <span>First Detected:</span>
                            <span className="text-text-primary">
                              {flagDetail.persistent_source?.first_seen || 'N/A'}
                            </span>
                          </div>
                          <div className="flex justify-between text-text-muted">
                            <span>Last Detected:</span>
                            <span className="text-text-primary">
                              {flagDetail.persistent_source?.last_seen || 'N/A'}
                            </span>
                          </div>
                          <div className="flex justify-between text-text-muted">
                            <span>Cluster Status:</span>
                            <span className="text-emerald-400 font-medium capitalize">
                              {flagDetail.persistent_source?.status || 'Unknown'}
                            </span>
                          </div>
                        </div>

                        {/* Case Note */}
                        {flagDetail.case_note && (
                          <div className="bg-panel/40 p-2.5 rounded border border-border">
                            <span className="text-[10px] uppercase font-semibold text-text-muted block mb-1">
                              Analyst Note
                            </span>
                            <p className="text-xs text-text-primary italic">
                              "{flagDetail.case_note}"
                            </p>
                          </div>
                        )}

                        <div className="text-[10px] text-text-muted italic text-center pt-1">
                          Map centered on cluster • Read-only view
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            );
          })}
      </div>
    </div>
  );
}

export default FlaggedPanel;
