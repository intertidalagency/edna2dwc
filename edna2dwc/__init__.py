import os

RETURN_FREED_MEMORY_AT_ONCE = "dirty_decay_ms:0,muzzy_decay_ms:0"

os.environ.setdefault("DUCKDB_JE_MALLOC_CONF", RETURN_FREED_MEMORY_AT_ONCE)
