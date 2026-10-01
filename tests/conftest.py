import os

os.environ.setdefault("DB_HOST", "test.invalid")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASS", "test")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("API_KEY_SECRET", "api-test-secret")
os.environ.setdefault("CACHE_REFRESH_SECRET", "refresh-test-secret")
