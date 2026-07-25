import mongomock
import pytest
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.config import settings


@pytest.fixture(autouse=True)
def _patch_mongo(monkeypatch):
    monkeypatch.setattr(settings, "mongo_uri", "mongodb://localhost:27017")
    monkeypatch.setattr(settings, "mongo_db", "test_ulpbot")


@pytest.fixture
async def db():
    client = mongomock.MongoClient()
    database: AsyncIOMotorDatabase = client["test_ulpbot"]
    yield database
    client.close()
