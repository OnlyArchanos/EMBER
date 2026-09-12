# Demo Script & Pre-Demo Checklist

This is the operational checklist and presentation script for the EMBER Fire Detection system demo.

---

## 1. Pre-Demo Setup Checklist (Mandatory)

Follow these steps on the demo machine before every rehearsal or live presentation:

### Step 1: Re-seed Demo Data (Crucial)

```bash
# Run from backend/
python scripts/seed_demo_data.py
```

**Always re-run `python scripts/seed_demo_data.py` before every demo.**

- **Why:** The persistence detection logic evaluates cluster recency against `today` (marking sources older than 7 days as `ended`). `seed_demo_data.py` clears any prior state, preserves relative day-spacing between all detections, and dynamically anchors the latest detection to yesterday relative to the current clock at load time. Running this ensures that active persistent sources and open flagged cases are always fresh and active on demo day.

### Step 2: Start the Backend

```bash
# Run from backend/
python -m uvicorn app.main:app --reload
```

- Verify startup logs show:
  1. `Model artifact loaded ... (score_min=0.3564, score_max=0.7777)`
  2. `Startup classification completed: 249 fires classified`
  3. `Startup persistence completed: 6 persistent sources updated`
  4. `Startup flagging completed: 4 flagged cases processed`
  5. `Uvicorn running on http://127.0.0.1:8000`

### Step 3: Quick Sanity Verification

Run a quick HTTP check or open in browser:

- `http://127.0.0.1:8000/api/health` -> `{"status": "ok", "mode": "seed"}`
- `http://127.0.0.1:8000/api/fires` -> 249 classified fires returned
- `http://127.0.0.1:8000/api/flags` -> 4 open flagged cases returned

### Step 4: Start the Frontend

```bash
# Run from frontend/
npm run dev
```

- Open `http://localhost:5173` in browser.

### Step 5: Offline Proof (Rehearsal Requirement)

- Disconnect Wi-Fi / network.
- Confirm all maps, filters, stats, and flagged cases render smoothly with zero network requests outside `localhost` (RULES.md §1, rule 3).

---

## 2. Presentation Walkthrough Script

1. **Dashboard Overview**:
   - Point out satellite data ingestion attribution (NASA FIRMS VIIRS) and OSM zone data attribution.
   - Show summary stats (total fires, breakdown by industrial, agricultural, wildfire, unclassified).

2. **Classification & Zone Overlay**:
   - Toggle zone overlays (industrial, forest, farmland polygons).
   - Show fire points classified by spatial containment (e.g. industrial fires inside refinery clusters).

3. **Persistent Heat Sources & DBSCAN Clustering**:
   - Explain how multi-day thermal detections are clustered using Haversine DBSCAN.
   - Contrast transient fires (agricultural crop burning, brief flare-ups) with persistent heat sources (stable multi-day emissions).

4. **Headline Feature: The Flagged Panel**:
   - Highlight open flagged cases: unexplained persistent heat sources located outside mapped industrial zones.
   - Show the Isolation Forest ML anomaly score, distance to nearest known zone, and member detection history.
   - Explain analyst workflow: prioritizing unexplained persistent thermal anomalies for investigation.
