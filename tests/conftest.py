import pytest
from nsw_property_sales_data import db


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    db.create_database(path)
    return path
