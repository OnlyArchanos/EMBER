# SIH26162 — Complete Technical Brief
**AI-Based Detection and Classification of Industrial Fires and Persistent Thermal Sources**
**Using NASA FIRMS, OpenStreetMap & Satellite Data**
**Sponsored by: National Technical Research Organisation (NTRO)**

> This document is a self-contained technical handoff. Everything needed to implement this project from scratch is here.

---

## 1. Problem Statement (Plain English)

Build a web application that:
1. Pulls real-time satellite fire/thermal hotspot data from NASA for India
2. Classifies each fire as **Industrial**, **Wildfire**, or **Agricultural burning** by checking if it falls inside an industrial zone, forest, or farmland (using OpenStreetMap geography)
3. Displays the results on a **dark, interactive map dashboard** with statistics

The "AI" component is the spatial classification engine. The rest is data ingestion and visualization.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      DATA SOURCES                           │
│                                                             │
│   NASA FIRMS API          OpenStreetMap (Overpass API)      │
│   (fire hotspot CSVs)     (industrial/forest zone polygons) │
└──────────────┬─────────────────────┬───────────────────────┘
               │                     │
               ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    PYTHON BACKEND                           │
│                                                             │
│  1. fetch_firms.py     → downloads NASA fire CSV            │
│  2. fetch_osm.py       → downloads OSM zone polygons        │
│  3. classify.py        → spatial join → assigns fire type   │
│  4. scheduler.py       → runs pipeline every 24 hours       │
│  5. main.py (FastAPI)  → serves REST API endpoints          │
│  6. database.py        → SQLite/PostgreSQL storage          │
└──────────────────────────────┬──────────────────────────────┘
                               │  JSON over HTTP
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    REACT FRONTEND                           │
│                                                             │
│  MapView.jsx     → Mapbox GL JS dark satellite map          │
│  Sidebar.jsx     → stats cards, charts, filters             │
│  FirePopup.jsx   → click a marker → see fire details        │
│  Dashboard.jsx   → layout wrapper                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Data Source 1 — NASA FIRMS API

### What It Is
NASA FIRMS (Fire Information for Resource Management System) provides near-real-time active fire/hotspot detections from two satellites:
- **MODIS** (Terra + Aqua satellites) — 1km resolution, data since 2000
- **VIIRS** (Suomi NPP + NOAA-20) — 375m resolution, higher precision, preferred

NASA pre-processes the satellite infrared imagery and outputs clean tabular data. **You do not process any satellite imagery yourself.**

### API Key
- Register free at: https://firms.modaps.eosdis.nasa.gov/api/
- Instant approval. No credit card.
- Key format: `MAP_KEY=your_key_here`

### Exact API Endpoints

**Get active fires in the last N days for a country:**
```
GET https://firms.modaps.eosdis.nasa.gov/api/country/csv/{MAP_KEY}/VIIRS_SNPP_NRT/IND/{days}
```
- `{MAP_KEY}` = your API key
- `VIIRS_SNPP_NRT` = VIIRS near-real-time data (use this — highest resolution)
- `IND` = India country code
- `{days}` = 1, 2, 3, 7, or 10

**Example — last 7 days of VIIRS fire data for India:**
```
https://firms.modaps.eosdis.nasa.gov/api/country/csv/YOUR_KEY/VIIRS_SNPP_NRT/IND/7
```

**Alternative — bounding box query (more precise for East/Central India):**
```
GET https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/VIIRS_SNPP_NRT/{lon_min},{lat_min},{lon_max},{lat_max}/{days}
```
India bounding box: `68.0,8.0,97.0,37.0`

**MODIS endpoint (alternative, larger dataset):**
```
https://firms.modaps.eosdis.nasa.gov/api/country/csv/{MAP_KEY}/MODIS_NRT/IND/7
```

### Raw CSV Column Schema (VIIRS)
```
latitude      → float  → fire center latitude
longitude     → float  → fire center longitude
bright_ti4    → float  → brightness temp channel 4 (Kelvin) — fire intensity
bright_ti5    → float  → brightness temp channel 5 (background)
frp           → float  → Fire Radiative Power (MW) — key indicator of intensity
scan          → float  → pixel scan size (km)
track         → float  → pixel track size (km)
acq_date      → date   → acquisition date (YYYY-MM-DD)
acq_time      → int    → acquisition time (HHMM UTC)
satellite     → str    → N (Suomi NPP) or 1 (NOAA-20)
instrument    → str    → VIIRS
confidence    → str    → 'l' (low), 'n' (nominal), 'h' (high)
version       → str    → dataset version
daynight      → str    → 'D' (day) or 'N' (night)
```

### MODIS CSV Column Schema (slightly different)
```
latitude, longitude, brightness, scan, track, acq_date, acq_time,
satellite, instrument, confidence (0-100 int), version, bright_t31, frp, daynight
```

### Key Fields to Use
- `latitude`, `longitude` — for map placement
- `frp` (Fire Radiative Power) — use for marker size/glow intensity on the map
- `confidence` — filter out low-confidence detections in production
- `acq_date` — for time-series charts

### Historical Data Download (for demo population)
```
https://firms.modaps.eosdis.nasa.gov/download/
```
- Select: VIIRS S-NPP → India → Last 3 months → CSV
- No API key needed for manual bulk download
- Use this to pre-populate your database before the hackathon demo

---

## 4. Data Source 2 — OpenStreetMap via Overpass API

### What It Is
OpenStreetMap is a free, open community-maintained map of the world. The Overpass API lets you query it programmatically for geographic polygons — industrial zones, forests, farmland, etc.

### No signup needed. Completely free and open.

### Overpass API Endpoint
```
POST https://overpass-api.de/api/interpreter
Content-Type: application/x-www-form-urlencoded
Body: data=<your_overpass_query>
```

Also accessible at the browser tool: https://overpass-turbo.eu/

### Queries You Need

**All industrial zones in India:**
```overpassql
[out:json][timeout:120];
area["name"="India"]->.india;
(
  way["landuse"="industrial"](area.india);
  relation["landuse"="industrial"](area.india);
);
out geom;
```

**All forest areas in India:**
```overpassql
[out:json][timeout:120];
area["name"="India"]->.india;
(
  way["landuse"="forest"](area.india);
  way["natural"="wood"](area.india);
  relation["landuse"="forest"](area.india);
);
out geom;
```

**All farmland/agriculture in India:**
```overpassql
[out:json][timeout:120];
area["name"="India"]->.india;
(
  way["landuse"="farmland"](area.india);
  way["landuse"="orchard"](area.india);
);
out geom;
```

**Specific industrial facilities (refineries, steel plants — better precision):**
```overpassql
[out:json][timeout:120];
area["name"="India"]->.india;
(
  way["industrial"="refinery"](area.india);
  way["industrial"="steel"](area.india);
  way["man_made"="works"](area.india);
  node["industrial"="refinery"](area.india);
);
out geom;
```

### Important Note on OSM Coverage
OSM industrial coverage in India is good for major sites (SAIL plants, HPCL/BPCL refineries, Tata Steel, RINL Vizag) but incomplete for smaller facilities. This is acceptable for a hackathon — mention it as a "known limitation" and "opportunity for improvement."

### Converting Overpass Output to GeoJSON
Overpass returns JSON. Convert to GeoJSON with the `overpass-to-geojson` npm package or the Python library `osmtogeojson`. GeoPandas can also read this directly:

```python
import geopandas as gpd
industrial_zones = gpd.read_file('industrial_india.geojson')
```

---

## 5. Core Classification Logic (Python)

### Library: GeoPandas
GeoPandas extends pandas to understand geometry (points, lines, polygons). The spatial join is the heart of the entire backend.

```python
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

def classify_fires(fires_df, industrial_gdf, forest_gdf, farmland_gdf):
    """
    fires_df: pandas DataFrame from NASA FIRMS CSV
    industrial_gdf, forest_gdf, farmland_gdf: GeoPandas GeoDataFrames from OSM
    Returns: fires_df with a new 'fire_type' column
    """
    
    # Step 1: Convert fire points to GeoDataFrame
    geometry = [Point(xy) for xy in zip(fires_df['longitude'], fires_df['latitude'])]
    fires_gdf = gpd.GeoDataFrame(fires_df, geometry=geometry, crs='EPSG:4326')
    
    # Step 2: Ensure all layers use same coordinate system
    industrial_gdf = industrial_gdf.to_crs('EPSG:4326')
    forest_gdf = forest_gdf.to_crs('EPSG:4326')
    farmland_gdf = farmland_gdf.to_crs('EPSG:4326')
    
    # Step 3: Spatial join — which fires fall inside industrial zones?
    industrial_fires = gpd.sjoin(
        fires_gdf, 
        industrial_gdf[['geometry']], 
        how='inner', 
        predicate='within'
    )
    industrial_ids = set(industrial_fires.index)
    
    # Step 4: Which fires fall inside forests?
    forest_fires = gpd.sjoin(
        fires_gdf, 
        forest_gdf[['geometry']], 
        how='inner', 
        predicate='within'
    )
    forest_ids = set(forest_fires.index)
    
    # Step 5: Assign classification (priority: industrial > forest > farmland > unknown)
    def assign_type(idx):
        if idx in industrial_ids:
            return 'industrial'
        elif idx in forest_ids:
            return 'wildfire'
        else:
            return 'agricultural'  # default for unclassified
    
    fires_df['fire_type'] = [assign_type(i) for i in fires_df.index]
    return fires_df
```

### Why DBSCAN for "Persistent" Source Detection (The AI Part)
A one-time fire is different from a persistent thermal source (like an industrial furnace or gas flare that burns continuously). DBSCAN clusters spatially close fire detections over time — a cluster with detections on many different days = persistent industrial source.

```python
from sklearn.cluster import DBSCAN
import numpy as np

def find_persistent_sources(fires_df, eps_km=0.5, min_days=7):
    """
    Identifies fire points that recur in the same location over multiple days.
    eps_km: radius in km to consider fires as 'same location'
    min_days: minimum unique days a location must appear to be 'persistent'
    """
    coords = fires_df[['latitude', 'longitude']].values
    
    # Convert km to radians for haversine metric
    eps_rad = eps_km / 6371.0
    
    db = DBSCAN(eps=eps_rad, min_samples=3, algorithm='ball_tree', metric='haversine')
    fires_df['cluster_id'] = db.fit_predict(np.radians(coords))
    
    # Count unique detection days per cluster
    cluster_days = fires_df.groupby('cluster_id')['acq_date'].nunique()
    persistent_clusters = cluster_days[cluster_days >= min_days].index
    
    fires_df['is_persistent'] = fires_df['cluster_id'].isin(persistent_clusters)
    return fires_df
```

**Persistent + industrial = almost certainly a steel plant flare or refinery.**
**Persistent + unclassified location = flag for NTRO investigation.** This is the "AI insight" that impresses judges.

---

## 6. Backend — FastAPI Structure

### File Structure
```
backend/
├── main.py              # FastAPI app, all route definitions
├── database.py          # SQLite/PostgreSQL connection + models
├── fetch_firms.py       # NASA FIRMS data fetching
├── fetch_osm.py         # OpenStreetMap polygon fetching
├── classify.py          # Classification logic (spatial join + DBSCAN)
├── scheduler.py         # APScheduler — auto-fetch every 24h
├── requirements.txt     # All Python dependencies
└── data/
    ├── industrial.geojson
    ├── forest.geojson
    └── farmland.geojson
```

### requirements.txt
```
fastapi==0.111.0
uvicorn==0.30.1
geopandas==0.14.4
pandas==2.2.2
shapely==2.0.4
scikit-learn==1.5.0
requests==2.32.3
apscheduler==3.10.4
sqlalchemy==2.0.31
python-dotenv==1.0.1
```

### main.py — Core API
```python
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import pandas as pd
from database import get_fires, get_stats

app = FastAPI(title="SIH26162 Fire Detection API")

# Allow React frontend to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_methods=["GET"],
    allow_headers=["*"],
)

@app.get("/api/fires")
def list_fires(
    fire_type: Optional[str] = None,   # 'industrial', 'wildfire', 'agricultural'
    state: Optional[str] = None,
    date: Optional[str] = None,        # YYYY-MM-DD
    confidence: Optional[str] = None,  # 'high', 'nominal', 'low'
    persistent: Optional[bool] = None
):
    fires = get_fires(fire_type=fire_type, state=state, date=date, 
                      confidence=confidence, persistent=persistent)
    return {"fires": fires, "total": len(fires)}

@app.get("/api/stats")
def get_dashboard_stats():
    return get_stats()

@app.get("/api/fires/{fire_id}")
def get_fire_detail(fire_id: int):
    # Returns full detail for a single fire (for popup)
    pass

@app.get("/health")
def health_check():
    return {"status": "ok"}
```

### Running the Backend
```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
API docs auto-generated at: `http://localhost:8000/docs` (Swagger UI)

---

## 7. API Response Contracts (Frontend Must Follow These)

### GET /api/fires
```json
{
  "fires": [
    {
      "id": 1,
      "latitude": 22.2540,
      "longitude": 84.8590,
      "brightness": 342.5,
      "frp": 28.4,
      "confidence": "high",
      "fire_type": "industrial",
      "zone_name": "Rourkela Steel Plant",
      "state": "Odisha",
      "acq_date": "2026-08-24",
      "acq_time": "0715",
      "satellite": "VIIRS",
      "is_persistent": true,
      "cluster_id": 14
    }
  ],
  "total": 312,
  "last_updated": "2026-08-25T04:00:00Z"
}
```

### GET /api/stats
```json
{
  "total_fires_today": 43,
  "total_fires_7days": 312,
  "persistent_sources": 18,
  "by_type": {
    "industrial": 12,
    "wildfire": 18,
    "agricultural": 13
  },
  "by_state": [
    {"state": "Odisha", "count": 52},
    {"state": "Jharkhand", "count": 41},
    {"state": "Chhattisgarh", "count": 38},
    {"state": "Maharashtra", "count": 31}
  ],
  "trend_30_days": [
    {"date": "2026-07-26", "count": 38, "industrial": 11},
    {"date": "2026-07-27", "count": 41, "industrial": 13}
  ],
  "high_alert": [
    {
      "id": 47,
      "latitude": 17.6868,
      "longitude": 83.2185,
      "zone_name": "HPCL Vizag Refinery",
      "frp": 94.2,
      "confidence": "high",
      "fire_type": "industrial",
      "is_persistent": false
    }
  ]
}
```

---

## 8. Frontend — Map Implementation

### Mapbox GL JS Setup

**Get free API key:** https://account.mapbox.com/ → Create account → Copy default public token

**index.html head:**
```html
<link href='https://api.mapbox.com/mapbox-gl-js/v3.4.0/mapbox-gl.css' rel='stylesheet' />
<script src='https://api.mapbox.com/mapbox-gl-js/v3.4.0/mapbox-gl.js'></script>
```

### Core Map Component (React)
```jsx
import { useEffect, useRef } from 'react';
import mapboxgl from 'mapbox-gl';

mapboxgl.accessToken = 'YOUR_MAPBOX_TOKEN';

const FIRE_COLORS = {
  industrial: '#ff4500',   // deep orange-red
  wildfire: '#ff8c00',     // orange
  agricultural: '#ffd700'  // gold
};

export default function FireMap({ fires }) {
  const mapContainer = useRef(null);
  const map = useRef(null);

  useEffect(() => {
    if (map.current) return;

    map.current = new mapboxgl.Map({
      container: mapContainer.current,
      style: 'mapbox://styles/mapbox/dark-v11',  // Dark satellite style
      center: [82.0, 22.0],  // Center of India
      zoom: 4.5
    });

    map.current.on('load', () => {
      // Add fire points as a GeoJSON source
      map.current.addSource('fires', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] }
      });

      // Heatmap layer (underneath)
      map.current.addLayer({
        id: 'fires-heatmap',
        type: 'heatmap',
        source: 'fires',
        paint: {
          'heatmap-weight': ['interpolate', ['linear'], ['get', 'frp'], 0, 0, 100, 1],
          'heatmap-intensity': 1.5,
          'heatmap-color': [
            'interpolate', ['linear'], ['heatmap-density'],
            0, 'rgba(0,0,0,0)',
            0.2, 'rgba(255,69,0,0.3)',
            0.8, 'rgba(255,69,0,0.8)',
            1, 'rgba(255,255,0,1)'
          ],
          'heatmap-radius': 20,
          'heatmap-opacity': 0.7
        }
      });

      // Circle layer (fire dots)
      map.current.addLayer({
        id: 'fires-points',
        type: 'circle',
        source: 'fires',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['get', 'frp'],
            0, 4,
            50, 8,
            200, 14
          ],
          'circle-color': [
            'match', ['get', 'fire_type'],
            'industrial', '#ff4500',
            'wildfire', '#ff8c00',
            'agricultural', '#ffd700',
            '#ffffff'
          ],
          'circle-opacity': 0.85,
          'circle-blur': 0.3,
          // Glow effect via stroke
          'circle-stroke-width': 2,
          'circle-stroke-color': [
            'match', ['get', 'fire_type'],
            'industrial', 'rgba(255,69,0,0.5)',
            'wildfire', 'rgba(255,140,0,0.5)',
            'agricultural', 'rgba(255,215,0,0.5)',
            'rgba(255,255,255,0.3)'
          ],
          'circle-stroke-opacity': 0.6
        }
      });

      // Click popup
      map.current.on('click', 'fires-points', (e) => {
        const props = e.features[0].properties;
        new mapboxgl.Popup({ className: 'fire-popup' })
          .setLngLat(e.lngLat)
          .setHTML(`
            <div class="popup-content">
              <h3>${props.zone_name || 'Unknown Zone'}</h3>
              <span class="badge badge-${props.fire_type}">${props.fire_type.toUpperCase()}</span>
              ${props.is_persistent ? '<span class="badge badge-alert">⚠ PERSISTENT</span>' : ''}
              <div class="stats">
                <div><label>FRP</label><value>${props.frp} MW</value></div>
                <div><label>Confidence</label><value>${props.confidence}</value></div>
                <div><label>Detected</label><value>${props.acq_date}</value></div>
                <div><label>Satellite</label><value>${props.satellite}</value></div>
                <div><label>State</label><value>${props.state}</value></div>
              </div>
            </div>
          `)
          .addTo(map.current);
      });
    });
  }, []);

  // Update map when fires data changes
  useEffect(() => {
    if (!map.current || !fires) return;
    const source = map.current.getSource('fires');
    if (!source) return;

    const geojson = {
      type: 'FeatureCollection',
      features: fires.map(f => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [f.longitude, f.latitude] },
        properties: f
      }))
    };
    source.setData(geojson);
  }, [fires]);

  return <div ref={mapContainer} style={{ width: '100%', height: '100vh' }} />;
}
```

### Alternative: Deck.gl (More Impressive Visuals)
If the frontend dev wants even more impressive animations, Deck.gl (by Uber) runs on top of Mapbox and adds 3D fire columns, animated scatter plots, etc.
- Docs: https://deck.gl/
- Example: `HexagonLayer` for fire density visualization

---

## 9. Important Indian Industrial Locations to Hardcode/Verify

These major Indian industrial sites should appear classified correctly. Use them to verify your classification logic:

| Facility | Lat | Lon | Type |
|---|---|---|---|
| Rourkela Steel Plant (SAIL) | 22.254 | 84.859 | Industrial |
| Bhilai Steel Plant | 21.214 | 81.428 | Industrial |
| Tata Steel, Jamshedpur | 22.802 | 86.185 | Industrial |
| HPCL Vizag Refinery | 17.687 | 83.219 | Industrial |
| IOCL Paradip Refinery | 20.317 | 86.608 | Industrial |
| RINL Vizag Steel | 17.680 | 83.220 | Industrial |
| NALCO Angul | 20.840 | 85.095 | Industrial |

These are all on the **East Coast corridor** — directly relevant to the NTRO brief.

---

## 10. Supplementary Data Sources

### Reverse Geocoding (Getting State Name from Lat/Lon)
```
GET https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json
```
Free. No key needed. Returns state, district, etc.
Use to populate the `state` field in your database.

Rate limit: 1 request/second. Cache results — don't call per fire, call once when storing.

### Sentinel-2 Satellite Imagery (Optional — For Popup Thumbnails)
Provides actual satellite image tiles for a location. Adds visual wow to the popup.
- **Copernicus Browser:** https://browser.dataspace.copernicus.eu/ (free, needs registration)
- **Sentinel Hub:** https://www.sentinel-hub.com/ (free trial tier)
- API docs: https://documentation.dataspace.copernicus.eu/APIs/SentinelHub.html

For a hackathon, even static Sentinel-2 tiles embedded in the popup will look stunning.

### World Administrative Boundaries (India States Shapefile)
For state-level choropleth maps:
- Download: https://gadm.org/download_country.html → India → Shapefile
- Free, no signup
- Use `level=1` for states

---

## 11. Coordinate System Notes

**All data uses WGS84 (EPSG:4326)** — standard lat/lon. This is what NASA FIRMS, OSM, and Mapbox all use natively. You should NOT need to reproject anything unless doing distance calculations.

**If doing distance calculations** (e.g., "fires within 5km of a refinery"):
- Convert to EPSG:32643 (UTM Zone 43N — covers most of India) for metric distances
- GeoPandas: `gdf.to_crs('EPSG:32643')`
- Then use `.buffer(5000)` for a 5km buffer

---

## 12. Known Limitations (Be Ready to Answer These From Judges)

1. **OSM coverage is incomplete** — Many smaller industrial facilities in rural India aren't mapped in OSM. Mitigation: supplement with India's official industrial estate databases (NICDIT).
2. **FIRMS detects heat, not fire specifically** — A very hot industrial furnace looks the same as a fire to the satellite. This is a feature, not a bug — both matter to NTRO.
3. **Cloud cover blind spots** — Satellites can't see through thick clouds. This is a known limitation of all satellite-based fire systems globally.
4. **~3-hour data latency** — VIIRS NRT data is available ~3 hours after satellite overpass. Not truly "real-time." Mention this — don't hide it.
5. **MODIS vs VIIRS resolution** — MODIS is 1km resolution (may miss small fires), VIIRS is 375m (preferred). Use VIIRS as primary, MODIS as fallback.

---

## 13. Full List of External Resources

### APIs & Data
- NASA FIRMS API: https://firms.modaps.eosdis.nasa.gov/api/
- NASA FIRMS Map (visual reference): https://firms.modaps.eosdis.nasa.gov/map/
- NASA FIRMS Download Portal: https://firms.modaps.eosdis.nasa.gov/download/
- NASA FIRMS User Guide: https://firms.modaps.eosdis.nasa.gov/usfs/api/area/
- Overpass API: https://overpass-api.de/api/interpreter
- Overpass Turbo (visual query builder): https://overpass-turbo.eu/
- Nominatim Reverse Geocoding: https://nominatim.openstreetmap.org/
- GADM India Boundaries: https://gadm.org/download_country.html

### Mapbox
- Mapbox GL JS Docs: https://docs.mapbox.com/mapbox-gl-js/guides/
- Mapbox Style Spec (custom styling): https://docs.mapbox.com/style-spec/
- Mapbox Heatmap Tutorial: https://docs.mapbox.com/mapbox-gl-js/example/heatmap-layer/
- Mapbox Cluster Example: https://docs.mapbox.com/mapbox-gl-js/example/cluster/
- Free dark style: `mapbox://styles/mapbox/dark-v11`
- Free satellite style: `mapbox://styles/mapbox/satellite-streets-v12`

### Python Libraries
- GeoPandas docs: https://geopandas.org/en/stable/docs.html
- Shapely docs: https://shapely.readthedocs.io/
- FastAPI docs: https://fastapi.tiangolo.com/
- Scikit-learn DBSCAN: https://scikit-learn.org/stable/modules/generated/sklearn.cluster.DBSCAN.html
- APScheduler (task scheduling): https://apscheduler.readthedocs.io/
- SQLAlchemy: https://docs.sqlalchemy.org/

### Reference Reading (for domain understanding)
- FIRMS Active Fire FAQ: https://earthdata.nasa.gov/earth-observation-data/near-real-time/firms/faq
- VIIRS 375m active fire algorithm: https://viirsland.gsfc.nasa.gov/Products/NASA/FireVIIRS.html
- India industrial fire news (for case studies): Search "HPCL Vizag fire 2023", "Rourkela Steel Plant incident"

---

## 14. Environment Variables (.env file)
```
NASA_FIRMS_API_KEY=your_key_here
MAPBOX_TOKEN=your_mapbox_public_token
DATABASE_URL=sqlite:///./fires.db
FETCH_INTERVAL_HOURS=24
INDIA_BBOX=68.0,8.0,97.0,37.0
```
