import os

import psycopg2
import pytest


@pytest.fixture(scope="session")
def dsn() -> str:
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set TEST_DATABASE_URL to a Postgres instance (see README)")
    return value


@pytest.fixture()
def conn(dsn):
    connection = psycopg2.connect(dsn)
    yield connection
    connection.close()
