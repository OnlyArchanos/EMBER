import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import FireDetection, Zone
from app.services.classifier import classify_fires


@pytest.fixture()
def db_session() -> Session:
    """In-memory SQLite session for isolated model-level tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def test_classify_fires_happy_path(db_session: Session):
    # Setup zones
    industrial_zone = Zone(
        zone_type="industrial",
        geometry="POLYGON ((9 9, 11 9, 11 11, 9 11, 9 9))"
    )
    forest_zone = Zone(
        zone_type="forest",
        geometry="POLYGON ((19 19, 21 19, 21 21, 19 21, 19 19))"
    )
    farmland_zone = Zone(
        zone_type="farmland",
        geometry="POLYGON ((29 29, 31 29, 31 31, 29 31, 29 29))"
    )
    db_session.add_all([industrial_zone, forest_zone, farmland_zone])
    db_session.commit()

    # Setup fires
    f1 = FireDetection(
        latitude=10.0, longitude=10.0, brightness=300.0, frp=10.0, 
        acq_date=datetime.date.today(), acq_time="1200", daynight="d", 
        satellite="snpp", confidence="n", fire_type="pending"
    )
    f2 = FireDetection(
        latitude=20.0, longitude=20.0, brightness=300.0, frp=10.0, 
        acq_date=datetime.date.today(), acq_time="1200", daynight="d", 
        satellite="snpp", confidence="n", fire_type="pending"
    )
    f3 = FireDetection(
        latitude=30.0, longitude=30.0, brightness=300.0, frp=10.0, 
        acq_date=datetime.date.today(), acq_time="1200", daynight="d", 
        satellite="snpp", confidence="n", fire_type="pending"
    )
    db_session.add_all([f1, f2, f3])
    db_session.commit()

    # Run classifier
    count = classify_fires(db_session)
    assert count == 3
    
    # Assert
    db_session.refresh(f1)
    db_session.refresh(f2)
    db_session.refresh(f3)
    assert f1.fire_type == "industrial"
    assert f2.fire_type == "wildfire"
    assert f3.fire_type == "agricultural"


def test_classify_fires_unclassified_fallback(db_session: Session):
    # Setup a zone
    industrial_zone = Zone(
        zone_type="industrial",
        geometry="POLYGON ((9 9, 11 9, 11 11, 9 11, 9 9))"
    )
    db_session.add(industrial_zone)
    db_session.commit()

    # Setup a fire outside any zone
    f1 = FireDetection(
        latitude=0.0, longitude=0.0, brightness=300.0, frp=10.0, 
        acq_date=datetime.date.today(), acq_time="1200", daynight="d", 
        satellite="snpp", confidence="n", fire_type="pending"
    )
    db_session.add(f1)
    db_session.commit()

    count = classify_fires(db_session)
    assert count == 1
    
    db_session.refresh(f1)
    assert f1.fire_type == "unclassified"


def test_classify_fires_overlapping_zones(db_session: Session):
    # Setup overlapping zones
    farmland_zone = Zone(
        zone_type="farmland",
        geometry="POLYGON ((9 9, 11 9, 11 11, 9 11, 9 9))"
    )
    industrial_zone = Zone(
        zone_type="industrial",
        geometry="POLYGON ((9 9, 11 9, 11 11, 9 11, 9 9))"
    )
    # Insert farmland first, so it might appear first in sjoin results
    db_session.add_all([farmland_zone, industrial_zone])
    db_session.commit()

    # Setup fire in the middle
    f1 = FireDetection(
        latitude=10.0, longitude=10.0, brightness=300.0, frp=10.0, 
        acq_date=datetime.date.today(), acq_time="1200", daynight="d", 
        satellite="snpp", confidence="n", fire_type="pending"
    )
    db_session.add(f1)
    db_session.commit()

    classify_fires(db_session)
    
    db_session.refresh(f1)
    # industrial > farmland, so it must be industrial
    assert f1.fire_type == "industrial"


def test_classify_fires_overlapping_industrial_forest(db_session: Session):
    # Setup overlapping zones
    forest_zone = Zone(
        zone_type="forest",
        geometry="POLYGON ((9 9, 11 9, 11 11, 9 11, 9 9))"
    )
    industrial_zone = Zone(
        zone_type="industrial",
        geometry="POLYGON ((9 9, 11 9, 11 11, 9 11, 9 9))"
    )
    # Insert forest first, so it might appear first in sjoin results
    db_session.add_all([forest_zone, industrial_zone])
    db_session.commit()

    # Setup fire in the middle
    f1 = FireDetection(
        latitude=10.0, longitude=10.0, brightness=300.0, frp=10.0, 
        acq_date=datetime.date.today(), acq_time="1200", daynight="d", 
        satellite="snpp", confidence="n", fire_type="pending"
    )
    db_session.add(f1)
    db_session.commit()

    classify_fires(db_session)
    
    db_session.refresh(f1)
    # industrial > forest, so it must be industrial
    assert f1.fire_type == "industrial"
