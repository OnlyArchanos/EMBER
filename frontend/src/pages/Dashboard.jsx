/**
 * Dashboard — Root page composing FireMap, Sidebar, and FlaggedPanel.
 *
 * Implements:
 * 1. Single unified initial fetch on mount (fires, zones, flags, stats).
 * 2. Full-viewport loading screen preventing partial component flash.
 * 3. Clear, actionable backend connection error state with retry.
 * 4. Cross-panel coordination: clicking a flagged card highlights and flies to the persistent source.
 * 5. Persistent attribution footer (NASA FIRMS, OpenStreetMap ODbL, CARTO).
 */

import { useEffect, useState, useCallback } from "react";
import { getFires, getZones, getFlags, getStats } from "../api/client.js";
import Sidebar from "../components/Sidebar.jsx";
import FireMap from "../components/FireMap.jsx";
import FlaggedPanel from "../components/FlaggedPanel.jsx";
import { colors } from "../theme.js";

export default function Dashboard() {
  const [fires, setFires] = useState([]);
  const [zones, setZones] = useState([]);
  const [flags, setFlags] = useState([]);
  const [stats, setStats] = useState(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Shared filter criteria
  const [filters, setFilters] = useState({
    fire_type: "",
    state: "",
    date_from: "",
    date_to: "",
  });

  // Cross-component coordination state
  const [selectedFlagId, setSelectedFlagId] = useState(null);
  const [selectedLocation, setSelectedLocation] = useState(null);

  // Single unified initial fetch across all 4 core endpoints
  const loadDashboardData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [firesRes, zonesRes, flagsRes, statsRes] = await Promise.all([
        getFires({ limit: 2000 }),
        getZones().catch((err) => {
          console.warn(
            "Zones non-fatal load warning (rendering map without overlays):",
            err,
          );
          return [];
        }),
        getFlags(),
        getStats({}),
      ]);

      setFires(Array.isArray(firesRes) ? firesRes : []);
      setZones(Array.isArray(zonesRes) ? zonesRes : []);
      setFlags(Array.isArray(flagsRes) ? flagsRes : []);
      setStats(statsRes);
      setLoading(false);
    } catch (err) {
      console.error("Failed to initialize dashboard data:", err);
      setError(err.message || "Could not connect to the backend server.");
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDashboardData();
  }, [loadDashboardData]);

  // Handle flag click from FlaggedPanel -> pans FireMap to centroid
  function handleFlagSelect(flagData) {
    setSelectedFlagId(flagData.flagId);
    if (flagData.latitude != null && flagData.longitude != null) {
      setSelectedLocation({
        latitude: flagData.latitude,
        longitude: flagData.longitude,
        zoom: 11,
      });
    }
  }

  // --- 1. Full-Viewport Loading State ---
  if (loading) {
    return (
      <div
        className="w-screen h-screen flex flex-col items-center justify-center select-none"
        style={{
          backgroundColor: colors.background,
          color: colors.textPrimary,
        }}
      >
        <div className="relative flex items-center justify-center mb-6">
          {/* Pulsing Radar Ring */}
          <div
            className="w-20 h-20 rounded-full border-2 border-dashed animate-spin"
            style={{
              borderColor: `${colors.accent}60`,
              animationDuration: "4s",
            }}
          />
          <div
            className="absolute w-12 h-12 rounded-full border-2 animate-ping"
            style={{ borderColor: colors.accent, animationDuration: "2s" }}
          />
          <div
            className="w-4 h-4 rounded-full"
            style={{
              backgroundColor: colors.accent,
              boxShadow: `0 0 16px ${colors.accent}`,
            }}
          />
        </div>

        <h1
          className="text-lg font-bold tracking-wider uppercase mb-1"
          style={{ color: colors.textPrimary }}
        >
          EMBER Thermal Intelligence Platform
        </h1>
        <p className="text-xs text-text-muted mb-4 tracking-wide">
          Connecting to satellite ingestion pipeline & spatial classifier...
        </p>

        <div className="flex items-center gap-3 text-xs text-text-muted">
          <span className="inline-block w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          <span>Synchronizing NASA FIRMS & OpenStreetMap datasets</span>
        </div>
      </div>
    );
  }

  // --- 2. Connection Error State with Retry Button ---
  if (error) {
    const apiBase =
      import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api";
    return (
      <div
        className="w-screen h-screen flex flex-col items-center justify-center p-6 select-none"
        style={{
          backgroundColor: colors.background,
          color: colors.textPrimary,
        }}
      >
        <div
          className="max-w-md w-full p-6 rounded-xl border space-y-4 shadow-2xl"
          style={{ backgroundColor: colors.panel, borderColor: colors.border }}
        >
          <div className="flex items-center gap-3">
            <div
              className="w-10 h-10 rounded-lg flex items-center justify-center text-xl font-bold"
              style={{
                backgroundColor: `${colors.danger}20`,
                color: colors.danger,
                border: `1px solid ${colors.danger}50`,
              }}
            >
              ⚠
            </div>
            <div>
              <h2 className="text-sm font-bold text-text-primary">
                Could not connect to backend
              </h2>
              <p className="text-xs text-text-muted">
                Backend connection failed during initial sync
              </p>
            </div>
          </div>

          <div
            className="p-3 rounded-lg border text-xs font-mono space-y-1"
            style={{
              backgroundColor: colors.background,
              borderColor: colors.border,
            }}
          >
            <div className="text-text-muted">Target Endpoint:</div>
            <div className="text-text-primary font-semibold break-all">
              {apiBase}
            </div>
            <div className="text-red-400 mt-2 text-[11px]">{error}</div>
          </div>

          <div className="text-xs text-text-muted leading-relaxed">
            Please ensure the FastAPI service is running locally on port 8000:
            <pre className="mt-2 p-2.5 rounded bg-black/50 border border-border text-emerald-400 text-[11px] overflow-x-auto">
              python -u -m uvicorn app.main:app --port 8000
            </pre>
          </div>

          <div className="pt-2 flex justify-end">
            <button
              onClick={loadDashboardData}
              className="px-4 py-2 rounded-lg text-xs font-semibold uppercase tracking-wider text-white transition-opacity hover:opacity-90 active:scale-95"
              style={{ backgroundColor: colors.accent }}
            >
              Retry Connection
            </button>
          </div>
        </div>
      </div>
    );
  }

  // --- 3. Main Operational Dashboard ---
  return (
    <div
      className="w-screen h-screen flex flex-col overflow-hidden select-none font-sans"
      style={{ backgroundColor: colors.background, color: colors.textPrimary }}
    >
      {/* Top Navigation / Brand Header */}
      <header
        className="h-12 border-b flex items-center justify-between px-4 z-20 shrink-0"
        style={{ backgroundColor: colors.panel, borderColor: colors.border }}
      >
        <div className="flex items-center gap-3">
          <div
            className="w-3 h-3 rounded-full animate-pulse"
            style={{
              backgroundColor: colors.accent,
              boxShadow: `0 0 8px ${colors.accent}`,
            }}
          />
          <span className="text-sm font-bold tracking-wide text-text-primary">
            EMBER
          </span>
          <span className="text-xs text-text-muted hidden sm:inline">
            / Industrial Thermal Intelligence & Anomaly Surveillance
          </span>
        </div>

        <div className="flex items-center gap-3">
          <div
            className="flex items-center gap-2 px-2.5 py-1 rounded-full border text-xs"
            style={{
              backgroundColor: colors.background,
              borderColor: colors.border,
            }}
          >
            <span className="w-2 h-2 rounded-full bg-emerald-500" />
            <span className="text-text-muted text-[11px]">Mode:</span>
            <span className="text-text-primary font-semibold text-[11px]">
              Seed Dataset (Gujarat)
            </span>
          </div>

          <div
            className="hidden md:flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs"
            style={{
              backgroundColor: colors.background,
              borderColor: colors.border,
            }}
          >
            <span className="text-text-muted text-[11px]">Hotspots:</span>
            <span
              className="text-accent font-mono font-semibold text-[11px]"
              style={{ color: colors.accent }}
            >
              {fires.length}
            </span>
          </div>
        </div>
      </header>

      {/* Main Workspace (3-Column Layout) */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* Left Side: Filter Controls, Filtered Breakdown & Global Metrics */}
        <Sidebar
          filters={filters}
          onFilterChange={setFilters}
          initialStats={stats}
        />

        {/* Center: Interactive Maplibre GL Satellite Map with Zone Overlays */}
        <main className="flex-1 h-full relative">
          <FireMap
            flags={flags}
            filters={filters}
            selectedLocation={selectedLocation}
            initialFires={fires}
            initialZones={zones}
          />
        </main>

        {/* Right Side: Ranked Unexplained Persistent Sources & Detail Drilldown */}
        <FlaggedPanel
          flags={flags}
          onFlagSelect={handleFlagSelect}
          selectedFlagId={selectedFlagId}
        />
      </div>

      {/* Persistent Visible Attribution Footer */}
      <footer
        className="h-7 border-t flex items-center justify-between px-4 text-[11px] text-text-muted z-20 shrink-0"
        style={{ backgroundColor: colors.panel, borderColor: colors.border }}
      >
        <div className="flex items-center gap-2">
          <span>Data sources:</span>
          <a
            href="https://firms.modaps.eosdis.nasa.gov/"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-text-primary underline transition-colors"
          >
            NASA FIRMS (MODIS/VIIRS)
          </a>
          <span>·</span>
          <a
            href="https://www.openstreetmap.org/copyright"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-text-primary underline transition-colors"
          >
            OpenStreetMap contributors (ODbL)
          </a>
          <span>·</span>
          <a
            href="https://carto.com/attributions"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-text-primary underline transition-colors"
          >
            CARTO Dark Matter
          </a>
        </div>

        <div className="hidden sm:flex items-center gap-2 text-[10px] text-text-muted">
          <span>NTRO Problem Statement EMBER</span>
          <span>·</span>
          <span>Offline Demo Ready</span>
        </div>
      </footer>
    </div>
  );
}
