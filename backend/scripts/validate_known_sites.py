import os
import sys
import datetime

# Add backend directory to sys.path so we can import app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy.orm import Session
from app.database import engine, Base
from app.models import FireDetection, PersistentSource, Zone, FlaggedCase
from app.services.classifier import classify_fires
from app.services.persistence import run_persistence
from app.services.flagging import run_flagging
from app.ml.known_sites_fixture import load_known_sites, build_site_fixture
from app.ml.infer import load_model


def validate_known_sites():
    """
    Standing check: ensures known industrial sites are correctly classified
    as 'industrial' and not flagged as anomalies.

    Synthetic FireDetection rows are constructed via build_site_fixture() from
    app.ml.known_sites_fixture — the same function used by train.py's post-fit
    validation hook.  Both callers share one set of fixture constants so they
    cannot produce divergent synthetic data.
    """
    Base.metadata.create_all(bind=engine)

    # Load inference model so flagging can score persistent sources
    load_model()

    validation_sites = load_known_sites()

    with Session(engine) as db:
        today = datetime.date.today()

        for idx, site in enumerate(validation_sites):
            # build_site_fixture() is the single source of truth for detection
            # values (frp, brightness, daynight, satellite, confidence, count).
            # Pass today so last_seen is within the active window.
            # Detections are classified against the real OSM zones already loaded
            # into the database by seed_demo_data.py (or live ingestion).
            _, members = build_site_fixture(site, base_date=today, site_id=idx + 1)
            for m in members:
                db.add(m)
            db.commit()

        # Run pipeline
        print("Running classification...")
        classify_fires(db)

        print("Running persistence detection...")
        run_persistence(db, current_date=today)

        print("Running flagging...")
        run_flagging(db)

        # Validate results
        success_count = 0
        total_sites = len(validation_sites)

        for site in validation_sites:
            site_passed = True

            fires = db.query(FireDetection).where(FireDetection.latitude == site["lat"]).all()
            for f in fires:
                if f.fire_type != "industrial":
                    print(f"FAIL ({site['name']}): Fire {f.id} was classified as {f.fire_type}, expected 'industrial'.")
                    site_passed = False
                    break

            if not site_passed:
                continue

            cluster_id = fires[0].cluster_id
            ps = db.query(PersistentSource).where(PersistentSource.cluster_id == cluster_id).first()
            if not ps:
                print(f"FAIL ({site['name']}): PersistentSource not found.")
                continue

            if ps.zone_type_at_location != "industrial":
                print(f"FAIL ({site['name']}): PersistentSource zone_type_at_location is {ps.zone_type_at_location}, expected 'industrial'.")
                continue

            fc = db.query(FlaggedCase).where(FlaggedCase.persistent_source_id == ps.id).first()
            if fc:
                print(f"FAIL ({site['name']}): Was incorrectly flagged as an anomaly.")
                continue

            success_count += 1
            print(f"PASS ({site['name']}): Correctly classified as industrial and not flagged.")

        print(f"\nVALIDATION RESULT: {success_count}/{total_sites} known industrial sites correctly classified and not flagged.")

        # Cleanup: Remove only the synthetic validation records;
        # preserve underlying seeded zones and demo data.
        val_lats = [s["lat"] for s in validation_sites]
        val_fires = db.query(FireDetection).filter(FireDetection.latitude.in_(val_lats)).all()
        val_cluster_ids = {f.cluster_id for f in val_fires if f.cluster_id is not None}
        if val_cluster_ids:
            val_ps = db.query(PersistentSource).filter(PersistentSource.cluster_id.in_(val_cluster_ids)).all()
            val_ps_ids = [ps.id for ps in val_ps]
            if val_ps_ids:
                db.query(FlaggedCase).filter(FlaggedCase.persistent_source_id.in_(val_ps_ids)).delete(synchronize_session=False)
            db.query(PersistentSource).filter(PersistentSource.cluster_id.in_(val_cluster_ids)).delete(synchronize_session=False)
        db.query(FireDetection).filter(FireDetection.latitude.in_(val_lats)).delete(synchronize_session=False)
        db.commit()

        return success_count == total_sites


if __name__ == "__main__":
    success = validate_known_sites()
    if not success:
        sys.exit(1)
