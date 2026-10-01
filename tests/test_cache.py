import json

import pytest
from fastapi.testclient import TestClient

import main


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.locked = False

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, nx=False, ex=None):
        if nx and (self.locked or key in self.values):
            return False
        self.values[key] = value
        if key == main.BOGOTA_REFRESH_LOCK_KEY:
            self.locked = True
        return True

    def rename(self, source, destination):
        self.values[destination] = self.values.pop(source)

    def delete(self, key):
        self.values.pop(key, None)

    def eval(self, script, count, key, token):
        if self.values.get(key) == token:
            self.delete(key)
            self.locked = False
            return 1
        return 0


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "API_KEY_SECRETA", "api-test-secret")
    monkeypatch.setattr(main, "CACHE_REFRESH_SECRET", "refresh-test-secret")
    return TestClient(main.app)


def test_cache_hit_does_not_access_sql(client, monkeypatch):
    cache = FakeRedis()
    payload = {"version": 1, "cache_updated_at": "now", "centros": {}}
    cache.values[main.BOGOTA_CACHE_KEY] = json.dumps(payload)
    monkeypatch.setattr(main, "REDIS_CACHE_ENABLED", True)
    monkeypatch.setattr(main, "get_redis_client", lambda: cache)
    monkeypatch.setattr(main, "conectar_bd", lambda: pytest.fail("SQL no debe abrirse"))

    response = client.get(
        "/api/observatorio/sede-bogota", headers={"X-API-Key": "api-test-secret"}
    )
    assert response.status_code == 200
    assert response.json() == payload


def test_admin_authentication(client):
    assert client.post("/api/admin/cache/refresh").status_code == 401
    assert client.post(
        "/api/admin/cache/refresh", headers={"X-Cache-Refresh-Secret": "wrong"}
    ).status_code == 403


def test_successful_refresh_publishes_atomically(client, monkeypatch):
    cache = FakeRedis()
    payload = {
        "version": 1,
        "cache_updated_at": "2026-10-01T00:00:00+00:00",
        "centros": {name: {} for name in main.CENTRO_ID_MAPA},
    }
    monkeypatch.setattr(main, "get_redis_client", lambda: cache)
    monkeypatch.setattr(main, "conectar_bd", lambda: object())
    monkeypatch.setattr(main, "construir_consolidado_bogota", lambda engine: payload)

    response = client.post(
        "/api/admin/cache/refresh",
        headers={"X-Cache-Refresh-Secret": "refresh-test-secret"},
    )
    assert response.status_code == 200
    assert json.loads(cache.values[main.BOGOTA_CACHE_KEY]) == payload


def test_failed_refresh_preserves_previous_value(client, monkeypatch):
    cache = FakeRedis()
    cache.values[main.BOGOTA_CACHE_KEY] = "previous"
    monkeypatch.setattr(main, "get_redis_client", lambda: cache)
    monkeypatch.setattr(main, "conectar_bd", lambda: object())

    def fail(_):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(main, "construir_consolidado_bogota", fail)
    response = client.post(
        "/api/admin/cache/refresh",
        headers={"X-Cache-Refresh-Secret": "refresh-test-secret"},
    )
    assert response.status_code == 503
    assert cache.values[main.BOGOTA_CACHE_KEY] == "previous"


def test_concurrent_refresh_is_rejected(client, monkeypatch):
    cache = FakeRedis()
    cache.locked = True
    monkeypatch.setattr(main, "get_redis_client", lambda: cache)
    response = client.post(
        "/api/admin/cache/refresh",
        headers={"X-Cache-Refresh-Secret": "refresh-test-secret"},
    )
    assert response.status_code == 409


def test_legacy_center_endpoint_reads_shared_consolidated(client, monkeypatch):
    cache = FakeRedis()
    expected = {"indicators": [1]}
    cache.values[main.BOGOTA_CACHE_KEY] = json.dumps(
        {"version": 1, "cache_updated_at": "now", "centros": {"centro-kennedy": expected}}
    )
    monkeypatch.setattr(main, "REDIS_CACHE_ENABLED", True)
    monkeypatch.setattr(main, "get_redis_client", lambda: cache)
    monkeypatch.setattr(main, "conectar_bd", lambda: pytest.fail("SQL no debe abrirse"))
    response = client.get(
        "/api/observatorio/completo/centro-kennedy",
        headers={"X-API-Key": "api-test-secret"},
    )
    assert response.status_code == 200
    assert response.json() == expected


def test_builder_reuses_and_closes_one_connection(monkeypatch):
    class Connection:
        def execute(self, *args, **kwargs):
            return None

    class Context:
        def __init__(self):
            self.connection = Connection()
            self.closed = False

        def __enter__(self):
            return self.connection

        def __exit__(self, *args):
            self.closed = True

    class Engine:
        def __init__(self):
            self.calls = 0
            self.context = Context()

        def connect(self):
            self.calls += 1
            return self.context

    engine = Engine()
    seen = []
    monkeypatch.setattr(main, "obtener_configuracion", lambda db: {"anio": 2026})
    monkeypatch.setattr(
        main, "construir_datos_centro", lambda db, centro, config: seen.append(db) or {}
    )
    result = main.construir_consolidado_bogota(engine)
    assert engine.calls == 1
    assert engine.context.closed is True
    assert len(seen) == 5 and all(db is engine.context.connection for db in seen)
    assert set(result["centros"]) == set(main.CENTRO_ID_MAPA)
