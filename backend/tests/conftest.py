import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.services.seed import seed_if_empty

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://kitprep:kitprep@localhost:5451/kitprep_test",
)


@pytest.fixture(scope="session")
def pg_engine():
    """Real Postgres engine with the full schema. Skips db-marked tests when
    the server is unreachable (row-lock semantics cannot run on sqlite)."""
    base, _, dbname = TEST_DATABASE_URL.rpartition("/")
    try:
        admin = create_engine(base + "/postgres", isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": dbname},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{dbname}"'))
        admin.dispose()
        eng = create_engine(TEST_DATABASE_URL)
        with eng.connect():
            pass
    except SQLAlchemyError:
        pytest.skip("PostgreSQL test database unreachable")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _require_pg(request):
    if request.node.get_closest_marker("db"):
        request.getfixturevalue("pg_engine")


@pytest.fixture
def SessionFactory(pg_engine):
    return sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)


@pytest.fixture
def db(pg_engine, SessionFactory):
    table_names = ", ".join(Base.metadata.tables)
    with pg_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
    session = SessionFactory()
    seed_if_empty(session)
    yield session
    session.close()


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient
    from app.main import app

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    # Instantiated without a context manager so the lifespan (which points at
    # the app's configured DATABASE_URL) is not triggered; schema already exists
    # in the test database via the pg_engine fixture.
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()
