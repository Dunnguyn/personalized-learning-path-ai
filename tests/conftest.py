import copy
import os
from datetime import datetime, timezone

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017/personalized_learning_path_test")
os.environ.setdefault("MONGO_URI", os.environ["MONGODB_URI"])
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-at-least-32-chars")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")

from backend.main import app
from backend.app.api.auth import get_current_user

TEST_USER_ID = "507f1f77bcf86cd799439011"
TEST_USER_INT_ID = 1


def build_auth_user():
    return {
        "_id": TEST_USER_ID,
        "user_id": TEST_USER_INT_ID,
        "email": "tester@example.com",
        "name": "Test User",
        "level": "beginner",
        "created_at": datetime.now(timezone.utc),
    }


class FakeInsertResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class FakeUpdateResult:
    def __init__(self, matched_count=0):
        self.matched_count = matched_count


class FakeDeleteResult:
    def __init__(self, deleted_count=0):
        self.deleted_count = deleted_count


class FakeCursor:
    def __init__(self, items):
        self.items = list(items)

    def sort(self, field, direction):
        reverse = direction == -1
        self.items.sort(key=lambda item: item.get(field), reverse=reverse)
        return self

    def skip(self, count):
        self.items = self.items[count:]
        return self

    def limit(self, count):
        self.items = self.items[:count]
        return self

    def __iter__(self):
        return iter(self.items)


def _matches_value(actual, expected):
    if isinstance(expected, dict):
        if "$regex" in expected:
            import re

            flags = re.IGNORECASE if expected.get("$options") == "i" else 0
            return re.search(expected["$regex"], str(actual or ""), flags) is not None
        if "$in" in expected:
            return actual in expected["$in"]
        if "$gte" in expected and (actual is None or actual < expected["$gte"]):
            return False
        if "$lt" in expected and (actual is None or actual >= expected["$lt"]):
            return False
        return True
    if isinstance(actual, ObjectId) or isinstance(expected, ObjectId):
        return str(actual) == str(expected)
    return actual == expected


def _matches(document, query):
    query = query or {}
    for key, expected in query.items():
        if not _matches_value(document.get(key), expected):
            return False
    return True


def _apply_projection(document, projection):
    if projection is None:
        return copy.deepcopy(document)

    include_keys = {key for key, value in projection.items() if value and key != "_id"}
    if include_keys:
        projected = {key: copy.deepcopy(document.get(key)) for key in include_keys if key in document}
        if projection.get("_id", 1) and "_id" in document:
            projected["_id"] = copy.deepcopy(document["_id"])
        return projected

    excluded = {key for key, value in projection.items() if value == 0}
    return {key: copy.deepcopy(value) for key, value in document.items() if key not in excluded}


class FakeCollection:
    def __init__(self, initial=None):
        self.items = [copy.deepcopy(item) for item in (initial or [])]

    def find_one(self, query=None, projection=None):
        for item in self.items:
            if _matches(item, query):
                return _apply_projection(item, projection)
        return None

    def find(self, query=None, projection=None):
        results = [_apply_projection(item, projection) for item in self.items if _matches(item, query)]
        return FakeCursor(results)

    def insert_one(self, document):
        payload = copy.deepcopy(document)
        payload.setdefault("_id", ObjectId())
        self.items.append(payload)
        return FakeInsertResult(payload["_id"])

    def update_one(self, query, update):
        for item in self.items:
            if _matches(item, query):
                if "$set" in update:
                    item.update(copy.deepcopy(update["$set"]))
                return FakeUpdateResult(matched_count=1)
        return FakeUpdateResult(matched_count=0)

    def delete_one(self, query):
        for index, item in enumerate(self.items):
            if _matches(item, query):
                del self.items[index]
                return FakeDeleteResult(deleted_count=1)
        return FakeDeleteResult(deleted_count=0)

    def count_documents(self, query):
        return sum(1 for item in self.items if _matches(item, query))


class FakeDatabase:
    def __init__(self, collections=None):
        self._collections = {}
        for name, items in (collections or {}).items():
            self._collections[name] = FakeCollection(items)

    def __getattr__(self, name):
        if name not in self._collections:
            self._collections[name] = FakeCollection()
        return self._collections[name]

    def __getitem__(self, name):
        return getattr(self, name)

    def command(self, name):
        if name == "ping":
            return {"ok": 1}
        raise ValueError(f"Unsupported command: {name}")


@pytest.fixture
def auth_user():
    return build_auth_user()


@pytest.fixture
def client():
    app.dependency_overrides.clear()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def authed_client(client, auth_user):
    app.dependency_overrides[get_current_user] = lambda: auth_user
    return client
