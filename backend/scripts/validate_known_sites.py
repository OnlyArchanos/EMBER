import os
import sys

# Add backend directory to sys.path so we can import app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy.orm import Session
from app.database import engine, Base
from app.models import FireDetection, PersistentSource, Zone, FlaggedCase
from app.services.classifier import classify_fires
from app.services.persistence import run_persistence
from app.services.flagging import run_flagging
import datetime


def validate_known_sites():
    """
    Standing check: Ensures known industrial sites are correctly classified
    as 'industrial' and not flagged as anomalies.
    """
    Base.metadata.create_all(bind=engine)
    
    fixture_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'seed', 'known_industrial_sites.json')
    with open(fixture_path, 'r') as f:
        import json
        validation_sites = json.load(f)

    with Session(engine) as db:
        today = datetime.date.today()
        
        for site in validation_sites:
            zone = Zone(
                zone_type=site.get("zone_type", "industrial"),
                name=site["name"],
                geometry=site["geometry"]
            )
            db.add(zone)
            db.commit()
            
            for i in range(5):
                f = FireDetection(
                    latitude=site["lat"], longitude=site["lon"], brightness=300.0, frp=50.0,
                    acq_date=today - datetime.timedelta(days=i), acq_time="1200",
                    daynight="d", satellite="snpp", confidence="h", fire_type="pending"
                )
                db.add(f)
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
        
        # Cleanup
        db.query(FlaggedCase).delete()
        db.query(PersistentSource).delete()
        db.query(FireDetection).delete()
        db.query(Zone).where(Zone.name.in_([s["name"] for s in validation_sites])).delete()
        db.commit()
        
        return success_count == total_sites


if __name__ == "__main__":
    success = validate_known_sites()
    if not success:
        sys.exit(1)
