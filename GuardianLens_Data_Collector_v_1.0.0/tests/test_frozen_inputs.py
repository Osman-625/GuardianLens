"""Backup safety tests use synthetic files and databases only."""
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import uuid

from PIL import Image
import pytest

from guardianlens import frozen_inputs as freezing
from guardianlens.collection_handoff import (
    get_annotation_dataset_status, refresh_annotation_dataset_safely,
    schedule_annotation_dataset_refresh,
)
from guardianlens.frozen_input_checks import reconcile_handoff


@pytest.fixture
def collection(tmp_path):
    root = tmp_path / 'source'
    (root / 'data').mkdir(parents=True)
    (root / 'config').mkdir()
    (root / 'config/categories.yaml').write_text('categories:\n  - name: Phones\n')
    schema = Path(__file__).resolve().parents[1] / 'src/guardianlens/schema.sql'
    con = sqlite3.connect(root / 'data/collector.sqlite3')
    con.executescript(schema.read_text(encoding='utf-8'))
    con.execute('PRAGMA journal_mode=WAL')
    for number, status in enumerate(('approved', 'needs_attention')):
        key = str(uuid.uuid4())
        image_id = str(uuid.uuid4())
        relative = f'data/images/mudah/{key}/{image_id}.png'
        path = root / relative
        path.parent.mkdir(parents=True)
        buffer = io.BytesIO()
        Image.new('RGB', (128, 128), (number * 50, 50, 50)).save(buffer, format='PNG')
        data = buffer.getvalue()
        path.write_bytes(data)
        record = dict(listing_id=key, platform='mudah', marketplace_listing_id=str(number),
                      source_url='https://example.invalid/private-seller', source_url_hash=str(number),
                      title='Frozen phone', description='Original device description', category='Phones',
                      condition='Used', price=100 + number, currency='MYR', location_state=None,
                      account_age_days=100, seller_rating=4.7, review_count=200000,
                      active_listing_count=2, status=status, captured_at='2026-01-01T00:00:00',
                      created_at='2026-01-01T00:00:00', updated_at='2026-01-01T00:00:00')
        columns = ','.join(record)
        marks = ','.join('?' for _ in record)
        con.execute(f'INSERT INTO listings ({columns}) VALUES ({marks})', tuple(record.values()))
        con.execute('INSERT INTO images (image_id,listing_id,platform,storage_path,sha256,perceptual_hash,file_size_bytes,width,height,source_position,is_primary,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (image_id, key, 'mudah', relative, hashlib.sha256(data).hexdigest(), '0000000000000000', len(data), 128, 128, 0, 1, '2026-01-01'))
    con.commit()
    (root / '.env').write_text('FROZEN_TEST_SECRET=synthetic-only-private-marker\n')
    evidence = root / 'data/private/staging/orphan-evidence.json'
    evidence.parent.mkdir(parents=True)
    evidence.write_text('{"original": "all remaining evidence"}')
    try:
        yield root, con
    finally:
        con.close()


def test_freeze_preserves_wal_all_states_bytes_and_separates_private(collection):
    root, writer = collection
    before = freezing.observe(root)
    source_bytes = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (root / 'data').rglob('*')
                    if p.is_file() and p.suffix not in {'.sqlite3', '.sqlite3-wal', '.sqlite3-shm'}}
    snapshot = freezing.freeze(root, observation_seconds=0, progress=lambda _: None)
    verified = freezing.verify_snapshot(snapshot)
    assert verified['pass']
    assert verified['database']['quick_check'] == ['ok']
    assert freezing.observe(root)['database_fingerprint'] == before['database_fingerprint']
    for path, (data, modified) in source_bytes.items():
        assert path.read_bytes() == data
        assert path.stat().st_mtime_ns == modified
    manifest = json.loads((snapshot / 'manifest.json').read_text())
    assert manifest['counts']['listings'] == 2
    assert manifest['counts']['approved_annotation_test'] == 1
    assert len((snapshot / 'private/candidates/images.jsonl').read_text().splitlines()) == 1
    checks = [json.loads(line) for line in (snapshot / 'private/reports/approved_record_verification.jsonl').read_text().splitlines()]
    assert checks[0]['missing_required_fields'] == ['location_state']
    assert not checks[0]['strict_collection_gate_pass']
    assert any(f['code'] == 'possible_marketplace_app_metrics_not_seller_metrics' for f in checks[0]['findings'])
    assert checks[0]['semantic_correctness'] == 'unverified'
    assert (snapshot / 'private/secrets/.env').read_bytes() == (root / '.env').read_bytes()
    for path in (snapshot / 'public').rglob('*'):
        if path.is_file():
            assert b'synthetic-only-private-marker' not in path.read_bytes()
            assert b'https://example.invalid/private-seller' not in path.read_bytes()
            assert b'Original device description' not in path.read_bytes()
    restored = json.loads((snapshot / 'private/reports/restore_verification.json').read_text())
    assert restored['pass'] and restored['table_counts']['listings'] == 2
    assert not restored['application_started'] and not restored['secrets_installed']
    assert not (root / 'data/exports').exists()
    with freezing.read_only_database(root / 'data/collector.sqlite3') as readonly:
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            readonly.execute("UPDATE listings SET title='changed'")
    with pytest.raises(freezing.SnapshotError, match='new and separate'):
        freezing.restore_snapshot(snapshot, root)
    (snapshot / 'public/approved_index.csv').write_text('tampered')
    with pytest.raises(freezing.SnapshotError, match='verification failed'):
        freezing.verify_snapshot(snapshot)


def test_active_work_refuses_before_creating_a_package(collection):
    root, writer = collection
    writer.execute("UPDATE listings SET status='processing' WHERE status='needs_attention'")
    writer.commit()
    with pytest.raises(freezing.SnapshotError, match='Active or changing'):
        freezing.freeze(root, observation_seconds=0, progress=lambda _: None)
    assert not (root / 'data/backups').exists()


def test_changed_asset_keeps_failed_attempt_without_complete_manifest(collection, monkeypatch):
    root, _ = collection
    original = freezing.copy_inventory
    changed = False
    def copy_then_change(source, destination, entries, progress):
        nonlocal changed
        result = original(source, destination, entries, progress)
        if not changed:
            changed = True
            (root / 'data/private/staging/orphan-evidence.json').write_text('changed during capture')
        return result
    monkeypatch.setattr(freezing, 'copy_inventory', copy_then_change)
    with pytest.raises(freezing.SnapshotError, match='changed'):
        freezing.freeze(root, observation_seconds=0, progress=lambda _: None)
    attempts = list((root / 'data/backups/frozen_inputs').iterdir())
    assert len(attempts) == 1
    assert (attempts[0] / 'FAILED_ATTEMPT.json').exists()
    assert not (attempts[0] / 'manifest.json').exists()


def test_collection_callbacks_do_not_import_or_call_legacy_exporter(monkeypatch):
    from guardianlens import annotation_dataset
    def forbidden(*args, **kwargs):
        raise AssertionError('Automatic annotation export must be inactive')
    monkeypatch.setattr(annotation_dataset, 'refresh_annotation_dataset', forbidden)
    assert refresh_annotation_dataset_safely('review_approve')['state'] == 'disabled'
    assert schedule_annotation_dataset_refresh('review_approve') is None
    assert not get_annotation_dataset_status()['automatic_refresh_enabled']


def test_handoff_reconciliation_compares_values_and_ignores_zero_state_keys(tmp_path):
    handoff = tmp_path / 'handoff'
    (handoff / 'master').mkdir(parents=True)
    (handoff / 'test').mkdir()
    (handoff / 'master/listings.csv').write_text('listing_id,status,price\none,approved,1.0\n')
    (handoff / 'test/annotation_test.csv').write_text('listing_id\none\n')
    (handoff / 'manifest.json').write_text(json.dumps({'files': {}, 'counts': {'by_status': {'approved': 1, 'captured': 0}}}))
    records = [{'listing_id': 'one', 'status': 'approved', 'price': 1.0}]
    assert reconcile_handoff(handoff, records, {'by_status': {'approved': 1}})['current']
    records[0]['price'] = 2.0
    result = reconcile_handoff(handoff, records, {'by_status': {'approved': 1}})
    assert not result['current']
    assert result['field_differences'] == [{'listing_id': 'one', 'field': 'price'}]


def test_handoff_reconciliation_checks_image_and_audit_membership(collection, tmp_path):
    root, _ = collection
    handoff = tmp_path / 'old-handoff'
    handoff.mkdir()
    (handoff / 'manifest.json').write_text('{"files": {}, "counts": {}}')
    con = freezing.read_only_database(root / 'data/collector.sqlite3')
    try:
        rows = [dict(r) for r in con.execute('SELECT * FROM listings')]
        result = reconcile_handoff(handoff, rows, {}, con)
    finally:
        con.close()
    assert not result['current']
    assert len(result['additional_csv_comparisons']['master/images.csv']['missing_ids']) == 2
    assert not result['additional_csv_comparisons']['audit/review_actions.csv']['file_present']
