from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading
import time

import pytest

from guardianlens.config import settings
from guardianlens.db import LATEST_SCHEMA_VERSION, MigrationError, init_db


def test_new_database_is_versioned_without_backup(isolated):
    path = isolated / "data" / "new.sqlite3"

    backup = init_db(path)

    assert backup is None
    con = sqlite3.connect(path)
    try:
        assert con.execute("PRAGMA user_version").fetchone()[0] == LATEST_SCHEMA_VERSION
        assert con.execute("SELECT name FROM schema_migrations WHERE version=1").fetchone()[0] == "baseline_versioned_schema"
        assert con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        con.close()


def test_unversioned_database_is_backed_up_and_preserved(isolated):
    path = isolated / "data" / "legacy.sqlite3"
    con = sqlite3.connect(path)
    try:
        con.executescript((settings.root / "src" / "guardianlens" / "schema.sql").read_text(encoding="utf-8"))
        con.execute(
            """
            INSERT INTO listings(
                listing_id,platform,source_url,source_url_hash,status,
                captured_at,created_at,updated_at
            ) VALUES('legacy','carousell','https://example.test/legacy','legacy-hash',
                     'captured','2026-01-01','2026-01-01','2026-01-01')
            """
        )
        con.commit()
        assert con.execute("PRAGMA user_version").fetchone()[0] == 0
    finally:
        con.close()

    backup = init_db(path)

    assert backup is not None and backup.is_file()
    migrated = sqlite3.connect(path)
    preserved = sqlite3.connect(backup)
    try:
        assert migrated.execute("PRAGMA user_version").fetchone()[0] == LATEST_SCHEMA_VERSION
        assert migrated.execute("SELECT COUNT(*) FROM listings WHERE listing_id='legacy'").fetchone()[0] == 1
        assert preserved.execute("PRAGMA user_version").fetchone()[0] == 0
        assert preserved.execute("SELECT COUNT(*) FROM listings WHERE listing_id='legacy'").fetchone()[0] == 1
        assert preserved.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        migrated.close()
        preserved.close()


def test_failed_migration_rolls_back_and_keeps_valid_backup(isolated):
    path = isolated / "data" / "incompatible.sqlite3"
    con = sqlite3.connect(path)
    try:
        con.execute("CREATE TABLE listings(listing_id TEXT PRIMARY KEY)")
        con.execute("INSERT INTO listings(listing_id) VALUES('keep-me')")
        con.commit()
    finally:
        con.close()

    with pytest.raises(MigrationError, match="Pre-migration backup"):
        init_db(path)

    backups = list((path.parent / "backups" / "schema_migrations").glob("incompatible_v0_*.sqlite3"))
    assert len(backups) == 1
    original = sqlite3.connect(path)
    backup = sqlite3.connect(backups[0])
    try:
        assert [row[1] for row in original.execute("PRAGMA table_info(listings)")] == ["listing_id"]
        assert original.execute("SELECT listing_id FROM listings").fetchone()[0] == "keep-me"
        assert backup.execute("SELECT listing_id FROM listings").fetchone()[0] == "keep-me"
        assert original.execute("PRAGMA user_version").fetchone()[0] == 0
    finally:
        original.close()
        backup.close()


def test_migration_rejects_wrong_index_definition_and_preserves_original(isolated):
    path = isolated / "data" / "wrong-index.sqlite3"
    con = sqlite3.connect(path)
    try:
        con.executescript((settings.root / "src" / "guardianlens" / "schema.sql").read_text(encoding="utf-8"))
        con.execute("DROP INDEX ix_listings_status")
        con.execute("CREATE INDEX ix_listings_status ON listings(category)")
        con.commit()
    finally:
        con.close()

    with pytest.raises(MigrationError, match="ix_listings_status"):
        init_db(path)

    backups = list((path.parent / "backups" / "schema_migrations").glob("wrong-index_v0_*.sqlite3"))
    assert len(backups) == 1
    original = sqlite3.connect(path)
    try:
        columns = tuple(row[2] for row in original.execute("PRAGMA index_info(ix_listings_status)"))
        assert columns == ("category",)
        assert original.execute("PRAGMA user_version").fetchone()[0] == 0
        assert original.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 0
    finally:
        original.close()


def test_newer_database_is_rejected_without_runtime_mutation_or_backup(isolated):
    path = isolated / "data" / "future.sqlite3"
    con = sqlite3.connect(path)
    try:
        con.execute("CREATE TABLE future_data(value TEXT)")
        con.execute("INSERT INTO future_data(value) VALUES('preserve-me')")
        con.execute(f"PRAGMA user_version={LATEST_SCHEMA_VERSION + 1}")
        con.execute("PRAGMA journal_mode=DELETE")
        con.commit()
    finally:
        con.close()

    with pytest.raises(MigrationError, match="newer than supported"):
        init_db(path)

    untouched = sqlite3.connect(path)
    try:
        assert untouched.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert untouched.execute("SELECT value FROM future_data").fetchone()[0] == "preserve-me"
        assert untouched.execute("PRAGMA user_version").fetchone()[0] == LATEST_SCHEMA_VERSION + 1
    finally:
        untouched.close()
    backup_root = path.parent / "backups" / "schema_migrations"
    assert not backup_root.exists()


def test_v5_database_migrates_to_paced_seller_retry_schema_and_preserves_rows(isolated):
    path = isolated / "data" / "version-five.sqlite3"
    init_db(path)
    con = sqlite3.connect(path)
    try:
        con.execute("DROP TABLE live_verification_items")
        con.execute("DROP TABLE live_verification_runs")
        con.execute("DROP TABLE seller_retry_attempts")
        con.execute("DROP TABLE seller_retry_items")
        con.execute("DROP TABLE seller_retry_batches")
        con.execute("DELETE FROM schema_migrations WHERE version IN (6,7,8)")
        con.execute("PRAGMA user_version=5")
        con.execute(
            """INSERT INTO listings(
                   listing_id,platform,source_url,source_url_hash,status,
                   captured_at,created_at,updated_at
               ) VALUES('preserved-v5','mudah','https://www.mudah.my/item-123456.htm',
                        'preserved-v5-hash','needs_attention','2026-01-01',
                        '2026-01-01','2026-01-01')"""
        )
        con.commit()
    finally:
        con.close()

    backup = init_db(path)

    assert backup is not None and backup.is_file()
    migrated = sqlite3.connect(path)
    try:
        assert migrated.execute("PRAGMA user_version").fetchone()[0] == LATEST_SCHEMA_VERSION
        assert migrated.execute(
            "SELECT name FROM schema_migrations WHERE version=6"
        ).fetchone()[0] == "paced_seller_capture_retries"
        assert migrated.execute(
            "SELECT status FROM listings WHERE listing_id='preserved-v5'"
        ).fetchone()[0] == "needs_attention"
        tables = {
            row[0]
            for row in migrated.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'seller_retry_%'"
            )
        }
        assert tables == {
            "seller_retry_batches",
            "seller_retry_items",
            "seller_retry_attempts",
        }
        item_fks = {
            (row[3], row[2], row[4], row[6])
            for row in migrated.execute("PRAGMA foreign_key_list(seller_retry_items)")
        }
        assert ("listing_id", "listings", "listing_id", "SET NULL") in item_fks
    finally:
        migrated.close()


def test_v7_database_migrates_to_live_verification_schema_and_preserves_rows(isolated):
    path = isolated / "data" / "version-seven.sqlite3"
    init_db(path)
    con = sqlite3.connect(path)
    try:
        con.execute("DROP TABLE live_verification_items")
        con.execute("DROP TABLE live_verification_runs")
        con.execute("DELETE FROM schema_migrations WHERE version=8")
        con.execute("PRAGMA user_version=7")
        con.execute(
            """INSERT INTO listings(
                   listing_id,platform,source_url,source_url_hash,status,
                   captured_at,created_at,updated_at
               ) VALUES('preserved-v7','carousell','https://www.carousell.com.my/p/item-123456',
                        'preserved-v7-hash','approved','2026-01-01',
                        '2026-01-01','2026-01-01')"""
        )
        con.commit()
    finally:
        con.close()

    backup = init_db(path)

    assert backup is not None and backup.is_file()
    migrated = sqlite3.connect(path)
    try:
        assert migrated.execute("PRAGMA user_version").fetchone()[0] == LATEST_SCHEMA_VERSION
        assert migrated.execute(
            "SELECT name FROM schema_migrations WHERE version=8"
        ).fetchone()[0] == "live_listing_verification"
        assert migrated.execute(
            "SELECT status FROM listings WHERE listing_id='preserved-v7'"
        ).fetchone()[0] == "approved"
        tables = {
            row[0]
            for row in migrated.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'live_verification_%'"
            )
        }
        assert tables == {"live_verification_runs", "live_verification_items"}
        item_fks = {
            (row[3], row[2], row[4], row[6])
            for row in migrated.execute("PRAGMA foreign_key_list(live_verification_items)")
        }
        assert ("listing_id", "listings", "listing_id", "CASCADE") in item_fks
        assert ("run_id", "live_verification_runs", "run_id", "CASCADE") in item_fks
    finally:
        migrated.close()


def test_concurrent_migration_callers_converge_on_one_schema(isolated, monkeypatch):
    from guardianlens import db as db_module

    path = isolated / "data" / "concurrent.sqlite3"
    con = sqlite3.connect(path)
    try:
        con.executescript((settings.root / "src" / "guardianlens" / "schema.sql").read_text(encoding="utf-8"))
        con.commit()
    finally:
        con.close()

    first_migration_entered = threading.Event()
    allow_first_migration = threading.Event()
    original_apply = db_module._apply_migration

    def delayed_apply(connection, version, schema):
        if not first_migration_entered.is_set():
            first_migration_entered.set()
            assert allow_first_migration.wait(timeout=5)
        return original_apply(connection, version, schema)

    monkeypatch.setattr(db_module, "_apply_migration", delayed_apply)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(init_db, path)
        assert first_migration_entered.wait(timeout=5)
        second = pool.submit(init_db, path)
        time.sleep(0.2)  # Let the second caller observe v0 and wait for the write lock.
        allow_first_migration.set()
        assert first.result(timeout=10) is not None
        assert second.result(timeout=10) is not None

    migrated = sqlite3.connect(path)
    try:
        assert migrated.execute("PRAGMA user_version").fetchone()[0] == LATEST_SCHEMA_VERSION
        assert migrated.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=1").fetchone()[0] == 1
        assert migrated.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        migrated.close()
