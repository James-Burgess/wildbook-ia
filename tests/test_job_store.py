# -*- coding: utf-8 -*-
"""Tests for wbia.web.job_store — the SQLite WAL-mode job storage layer.

These are pure unit tests with no dependency on ZMQ, the collector process,
or the rest of the WBIA stack.  They exercise the JobStore class directly.

Placed in top-level tests/ to avoid triggering wbia.__init__ (which requires
utool and other heavy deps).  job_store.py is self-contained (stdlib only).
"""
import importlib.util
import json
import os
import pathlib
import sqlite3
import threading
import time
import uuid

import pytest

# Import job_store directly from file path to avoid triggering the heavy
# wbia.__init__ (which requires utool, etc.).  job_store.py is self-contained.
_job_store_path = str(
    pathlib.Path(__file__).resolve().parent.parent / 'wbia' / 'web' / 'job_store.py'
)
_spec = importlib.util.spec_from_file_location('job_store', _job_store_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
JobStore = _mod.JobStore


@pytest.fixture
def store(tmp_path):
    """Yield a fresh JobStore backed by a temp directory."""
    db_path = str(tmp_path / 'jobs.db')
    s = JobStore(db_path)
    yield s
    s.close()


@pytest.fixture
def db_path(tmp_path):
    """Return just the path (caller manages open/close)."""
    return str(tmp_path / 'jobs.db')


# ------------------------------------------------------------------
# Schema & creation
# ------------------------------------------------------------------

class TestCreateDB:
    def test_creates_file(self, tmp_path):
        db_path = str(tmp_path / 'jobs.db')
        assert not os.path.exists(db_path)
        store = JobStore(db_path)
        assert os.path.exists(db_path)
        store.close()

    def test_wal_mode(self, store):
        row = store._conn.execute('PRAGMA journal_mode').fetchone()
        assert row[0] == 'wal'

    def test_schema_has_jobs_table(self, store):
        row = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"
        ).fetchone()
        assert row is not None

    def test_idempotent_creation(self, db_path):
        """Opening the same db twice doesn't fail or drop data."""
        s1 = JobStore(db_path)
        s1.register_job('job1', 'completed', 1)
        s1.close()
        s2 = JobStore(db_path)
        assert s2.get_status('job1') == 'completed'
        s2.close()


# ------------------------------------------------------------------
# Basic CRUD
# ------------------------------------------------------------------

class TestRegisterJob:
    def test_register_and_read_status(self, store):
        store.register_job('j1', 'completed', 42)
        assert store.get_status('j1') == 'completed'

    def test_register_updates_existing(self, store):
        store.register_job('j1', 'received', 1)
        store.register_job('j1', 'completed', 1)
        assert store.get_status('j1') == 'completed'

    def test_job_exists(self, store):
        assert not store.job_exists('j1')
        store.register_job('j1', 'received', 1)
        assert store.job_exists('j1')


class TestUpdateStatus:
    def test_update(self, store):
        store.register_job('j1', 'received', 1)
        store.update_status('j1', 'working')
        assert store.get_status('j1') == 'working'

    def test_update_nonexistent_is_noop(self, store):
        store.update_status('ghost', 'completed')
        assert store.get_status('ghost') is None


class TestDeleteJob:
    def test_delete(self, store):
        store.register_job('j1', 'completed', 1)
        store.delete_job('j1')
        assert not store.job_exists('j1')

    def test_delete_nonexistent_is_noop(self, store):
        store.delete_job('ghost')  # should not raise

    def test_delete_jobs_batch(self, store):
        for i in range(5):
            store.register_job(f'j{i}', 'completed', i)
        store.delete_jobs(['j0', 'j2', 'j4'])
        assert store.job_exists('j1')
        assert store.job_exists('j3')
        assert not store.job_exists('j0')
        assert not store.job_exists('j2')
        assert not store.job_exists('j4')


# ------------------------------------------------------------------
# Metadata round-trip
# ------------------------------------------------------------------

def _make_metadata(jobcounter=1, action='query_chips_simple_dict'):
    return {
        'jobcounter': jobcounter,
        'action': action,
        'lane': 'slow',
        'callback_url': 'http://example.com/cb',
        'callback_method': 'POST',
        'callback_detailed': True,
        'request': {
            'endpoint': '/api/engine/query/chips/simple/dict/',
            'function': 'query_chips_simple_dict',
            'input': {'aid_list': [1, 2, 3]},
        },
        'args': ([1, 2, 3],),
        'kwargs': {'database_imgsetid': None},
        'times': {
            'received': '2024-01-15 10:00:00 PST',
        },
    }


class TestStoreMetadata:
    def test_round_trip(self, store):
        meta = _make_metadata(jobcounter=7)
        store.store_metadata('j1', meta)
        got = store.get_metadata('j1')
        assert got is not None
        assert got['jobcounter'] == 7
        assert got['action'] == 'query_chips_simple_dict'
        assert got['lane'] == 'slow'
        assert got['callback_url'] == 'http://example.com/cb'
        assert got['callback_detailed'] is True
        assert got['request']['endpoint'] == '/api/engine/query/chips/simple/dict/'
        assert got['args'] == [[1, 2, 3]]  # tuple→list via JSON
        assert got['kwargs'] == {'database_imgsetid': None}
        assert got['times']['received'] == '2024-01-15 10:00:00 PST'

    def test_upsert_updates_existing(self, store):
        store.store_metadata('j1', _make_metadata(jobcounter=1))
        store.store_metadata('j1', _make_metadata(jobcounter=2, action='detect'))
        got = store.get_metadata('j1')
        assert got['jobcounter'] == 2
        assert got['action'] == 'detect'

    def test_get_metadata_nonexistent(self, store):
        assert store.get_metadata('ghost') is None

    def test_get_metadata_returns_none_for_skeleton_row(self, store):
        """register_job creates a skeleton row — get_metadata should
        return None since there's no real metadata yet."""
        store.register_job('j1', 'completed', 5)
        assert store.get_metadata('j1') is None


# ------------------------------------------------------------------
# Times
# ------------------------------------------------------------------

class TestUpdateTimes:
    def test_update_times(self, store):
        store.store_metadata('j1', _make_metadata())
        store.update_times('j1', {
            'started': '2024-01-15 10:01:00 PST',
            'updated': '2024-01-15 10:01:00 PST',
        })
        times = store.get_times('j1')
        assert times['received'] == '2024-01-15 10:00:00 PST'
        assert times['started'] == '2024-01-15 10:01:00 PST'

    def test_update_times_preserves_existing(self, store):
        store.store_metadata('j1', _make_metadata())
        store.update_times('j1', {
            'started': '2024-01-15 10:01:00 PST',
            'updated': '2024-01-15 10:01:00 PST',
        })
        # Second update should NOT overwrite started
        store.update_times('j1', {
            'completed': '2024-01-15 10:05:00 PST',
            'updated': '2024-01-15 10:05:00 PST',
            'runtime': '0 hours 4 min. 0 sec. (total: 240 sec.)',
            'runtime_sec': 240,
        })
        times = store.get_times('j1')
        assert times['started'] == '2024-01-15 10:01:00 PST'
        assert times['completed'] == '2024-01-15 10:05:00 PST'
        assert times['runtime_sec'] == 240

    def test_get_times_nonexistent(self, store):
        assert store.get_times('ghost') == {}


# ------------------------------------------------------------------
# Results
# ------------------------------------------------------------------

class TestStoreResult:
    def test_round_trip(self, store):
        store.register_job('j1', 'completed', 1)
        result = {
            'exec_status': 'completed',
            'json_result': json.dumps({'score': 0.95}),
            'jobid': 'j1',
        }
        store.store_result('j1', result)
        got = store.get_result('j1')
        assert got is not None
        assert got['exec_status'] == 'completed'
        assert json.loads(got['json_result']) == {'score': 0.95}
        assert got['jobid'] == 'j1'

    def test_get_result_no_result_yet(self, store):
        store.register_job('j1', 'working', 1)
        assert store.get_result('j1') is None

    def test_get_result_nonexistent(self, store):
        assert store.get_result('ghost') is None

    def test_large_json_result(self, store):
        """Verify SQLite handles a 10 MB JSON blob correctly."""
        store.register_job('j1', 'completed', 1)
        big_data = {'data': 'x' * (10 * 1024 * 1024)}
        result = {
            'exec_status': 'completed',
            'json_result': json.dumps(big_data),
            'jobid': 'j1',
        }
        store.store_result('j1', result)
        got = store.get_result('j1')
        assert len(got['json_result']) > 10 * 1024 * 1024


# ------------------------------------------------------------------
# Batch operations
# ------------------------------------------------------------------

class TestRegisterBatch:
    def test_batch_register(self, store):
        entries = [
            {'jobid': f'j{i}', 'status': 'completed', 'jobcounter': i}
            for i in range(100)
        ]
        store.register_batch(entries)
        ids = store.get_job_ids()
        assert len(ids) == 100
        assert store.get_status('j0') == 'completed'
        assert store.get_status('j99') == 'completed'

    def test_batch_register_upserts(self, store):
        store.register_job('j0', 'received', 0)
        entries = [
            {'jobid': 'j0', 'status': 'completed', 'jobcounter': 0},
            {'jobid': 'j1', 'status': 'working', 'jobcounter': 1},
        ]
        store.register_batch(entries)
        assert store.get_status('j0') == 'completed'
        assert store.get_status('j1') == 'working'

    def test_batch_register_empty(self, store):
        store.register_batch([])
        assert store.get_job_ids() == []


# ------------------------------------------------------------------
# Job status dict (the main listing query)
# ------------------------------------------------------------------

class TestGetJobStatusDict:
    def test_returns_all_without_limit(self, store):
        for i in range(5):
            store.register_job(f'j{i}', 'completed', i)
        result = store.get_job_status_dict()
        assert len(result) == 5

    def test_limit_returns_most_recent(self, store):
        for i in range(50):
            store.register_job(f'j{i}', 'completed', i)
        result = store.get_job_status_dict(limit=10)
        assert len(result) == 10
        counters = [v['jobcounter'] for v in result.values()]
        # Should have the 10 highest counters (40-49)
        assert min(counters) == 40
        assert max(counters) == 49

    def test_includes_metadata_fields(self, store):
        meta = _make_metadata(jobcounter=5)
        store.store_metadata('j1', meta)
        result = store.get_job_status_dict()
        assert 'j1' in result
        entry = result['j1']
        assert entry['action'] == 'query_chips_simple_dict'
        assert entry['endpoint'] == '/api/engine/query/chips/simple/dict/'
        assert entry['function'] == 'query_chips_simple_dict'
        assert entry['time_received'] == '2024-01-15 10:00:00 PST'
        assert entry['lane'] == 'slow'

    def test_skeleton_rows_have_none_fields(self, store):
        """Batch-registered jobs should still show up with None fields."""
        store.register_job('j1', 'completed', 5)
        result = store.get_job_status_dict()
        entry = result['j1']
        assert entry['status'] == 'completed'
        assert entry['jobcounter'] == 5
        assert entry['action'] is None
        assert entry['endpoint'] is None


# ------------------------------------------------------------------
# get_job_ids, get_max_jobcounter
# ------------------------------------------------------------------

class TestGetJobIds:
    def test_sorted_by_counter(self, store):
        store.register_job('j_b', 'completed', 2)
        store.register_job('j_a', 'completed', 1)
        store.register_job('j_c', 'completed', 3)
        ids = store.get_job_ids()
        assert ids == ['j_a', 'j_b', 'j_c']


class TestGetMaxJobcounter:
    def test_empty(self, store):
        assert store.get_max_jobcounter() == 0

    def test_with_data(self, store):
        store.register_job('j1', 'completed', 42)
        store.register_job('j2', 'completed', 7)
        assert store.get_max_jobcounter() == 42


# ------------------------------------------------------------------
# Callback info
# ------------------------------------------------------------------

class TestGetCallbackInfo:
    def test_round_trip(self, store):
        meta = _make_metadata()
        store.store_metadata('j1', meta)
        url, method, detailed = store.get_callback_info('j1')
        assert url == 'http://example.com/cb'
        assert method == 'POST'
        assert detailed is True

    def test_nonexistent(self, store):
        url, method, detailed = store.get_callback_info('ghost')
        assert url is None
        assert method is None
        assert detailed is False


# ------------------------------------------------------------------
# Concurrent access (WAL mode)
# ------------------------------------------------------------------

class TestConcurrentAccess:
    def test_concurrent_readers(self, db_path):
        """Two connections can read simultaneously with WAL mode."""
        s1 = JobStore(db_path)
        s1.register_job('j1', 'completed', 1)

        # Open a second read-only connection
        conn2 = sqlite3.connect(db_path)
        conn2.execute('PRAGMA journal_mode=WAL')
        row = conn2.execute(
            'SELECT status FROM jobs WHERE jobid=?', ('j1',)
        ).fetchone()
        assert row[0] == 'completed'

        conn2.close()
        s1.close()

    def test_reader_doesnt_block_writer(self, db_path):
        """A reader holding a transaction doesn't block the writer."""
        s1 = JobStore(db_path)
        s1.register_job('j1', 'received', 1)

        # Open reader and start reading
        conn2 = sqlite3.connect(db_path)
        conn2.execute('PRAGMA journal_mode=WAL')
        conn2.execute('BEGIN')
        conn2.execute('SELECT * FROM jobs').fetchall()

        # Writer should still be able to write
        s1.update_status('j1', 'completed')
        assert s1.get_status('j1') == 'completed'

        conn2.execute('ROLLBACK')
        conn2.close()
        s1.close()


# ------------------------------------------------------------------
# Performance / bottleneck exposure
# ------------------------------------------------------------------

class TestPerformance:
    def test_batch_register_10k_jobs(self, store):
        """Batch registering 10K jobs should complete in <2 seconds."""
        entries = [
            {'jobid': str(uuid.uuid4()), 'status': 'completed', 'jobcounter': i}
            for i in range(10_000)
        ]
        start = time.monotonic()
        store.register_batch(entries)
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, f'Batch register took {elapsed:.2f}s (expected <2s)'
        assert len(store.get_job_ids()) == 10_000

    def test_status_dict_10k_with_limit(self, store):
        """Fetching 100 most recent from 10K jobs should be fast."""
        entries = [
            {'jobid': str(uuid.uuid4()), 'status': 'completed', 'jobcounter': i}
            for i in range(10_000)
        ]
        store.register_batch(entries)

        start = time.monotonic()
        result = store.get_job_status_dict(limit=100)
        elapsed = time.monotonic() - start
        assert len(result) == 100
        assert elapsed < 0.5, f'Status dict query took {elapsed:.2f}s (expected <0.5s)'

    def test_status_dict_10k_no_limit(self, store):
        """Fetching all 10K jobs status dict should still be <5s."""
        entries = [
            {'jobid': str(uuid.uuid4()), 'status': 'completed', 'jobcounter': i}
            for i in range(10_000)
        ]
        store.register_batch(entries)

        start = time.monotonic()
        result = store.get_job_status_dict(limit=0)
        elapsed = time.monotonic() - start
        assert len(result) == 10_000
        assert elapsed < 5.0, f'Status dict query took {elapsed:.2f}s (expected <5s)'

    def test_concurrent_read_throughput(self, db_path):
        """Multiple threads reading simultaneously should not serialize."""
        store = JobStore(db_path)
        for i in range(100):
            store.store_metadata(f'j{i}', _make_metadata(jobcounter=i))

        results = []
        errors = []

        def reader():
            try:
                conn = sqlite3.connect(db_path)
                conn.execute('PRAGMA journal_mode=WAL')
                for _ in range(50):
                    rows = conn.execute(
                        'SELECT jobid, status FROM jobs'
                    ).fetchall()
                    assert len(rows) == 100
                conn.close()
                results.append(True)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(8)]
        start = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.monotonic() - start

        assert not errors, f'Errors in reader threads: {errors}'
        assert len(results) == 8
        # 8 threads x 50 reads each — generous limit for slow filesystems (WSL2)
        assert elapsed < 30.0, f'Concurrent reads took {elapsed:.2f}s'
        store.close()

    def test_write_doesnt_block_reads_long(self, db_path):
        """A write transaction should not block readers for more than busy_timeout."""
        store = JobStore(db_path)
        store.register_job('j1', 'received', 1)

        read_times = []

        def timed_read():
            conn = sqlite3.connect(db_path)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA busy_timeout=5000')
            start = time.monotonic()
            row = conn.execute('SELECT status FROM jobs WHERE jobid=?', ('j1',)).fetchone()
            elapsed = time.monotonic() - start
            read_times.append(elapsed)
            conn.close()

        # Do a read while writer is active
        t = threading.Thread(target=timed_read)
        store.register_batch([
            {'jobid': f'big_{i}', 'status': 'completed', 'jobcounter': i}
            for i in range(5000)
        ])
        t.start()
        t.join()

        assert len(read_times) == 1
        # Read should complete nearly instantly with WAL
        assert read_times[0] < 1.0, f'Read during write took {read_times[0]:.3f}s'
        store.close()


# ------------------------------------------------------------------
# Vacuum
# ------------------------------------------------------------------

class TestVacuum:
    def test_vacuum_after_deletes(self, store):
        entries = [
            {'jobid': f'j{i}', 'status': 'completed', 'jobcounter': i}
            for i in range(100)
        ]
        store.register_batch(entries)
        store.delete_jobs([f'j{i}' for i in range(100)])
        store.vacuum()  # should not raise
        assert store.get_job_ids() == []


# ------------------------------------------------------------------
# ensure_job
# ------------------------------------------------------------------

class TestEnsureJob:
    def test_creates_new(self, store):
        store.ensure_job('j1', 'received')
        assert store.get_status('j1') == 'received'

    def test_does_not_overwrite(self, store):
        store.register_job('j1', 'completed', 5)
        store.ensure_job('j1', 'received')
        assert store.get_status('j1') == 'completed'


# ------------------------------------------------------------------
# Full lifecycle (simulates collector flow)
# ------------------------------------------------------------------

class TestFullLifecycle:
    def test_job_flow_receive_to_complete(self, store):
        """Simulate the full lifecycle of a job through the collector."""
        jobid = str(uuid.uuid4())
        meta = _make_metadata(jobcounter=42)

        # 1. Job received — ensure_job
        store.ensure_job(jobid, 'received')
        assert store.get_status(jobid) == 'received'

        # 2. Metadata arrives from engine
        store.store_metadata(jobid, meta)
        assert store.get_metadata(jobid) is not None

        # 3. Status notifications
        store.update_status(jobid, 'accepted')
        assert store.get_status(jobid) == 'accepted'

        store.update_status(jobid, 'queued')
        store.update_status(jobid, 'working')
        store.update_times(jobid, {
            'started': '2024-01-15 10:01:00 PST',
            'updated': '2024-01-15 10:01:00 PST',
        })

        # 4. Job completes
        store.update_status(jobid, 'completed')
        store.update_times(jobid, {
            'completed': '2024-01-15 10:05:00 PST',
            'updated': '2024-01-15 10:05:00 PST',
            'runtime': '0 hours 4 min. 0 sec. (total: 240 sec.)',
            'runtime_sec': 240,
            'turnaround': '0 hours 5 min. 0 sec. (total: 300 sec.)',
            'turnaround_sec': 300,
        })

        # 5. Result stored
        store.store_result(jobid, {
            'exec_status': 'completed',
            'json_result': json.dumps({'matches': [1, 2, 3]}),
            'jobid': jobid,
        })

        # 6. Verify everything reads back correctly
        status_dict = store.get_job_status_dict()
        entry = status_dict[jobid]
        assert entry['status'] == 'completed'
        assert entry['jobcounter'] == 42
        assert entry['time_started'] == '2024-01-15 10:01:00 PST'
        assert entry['time_completed'] == '2024-01-15 10:05:00 PST'
        assert entry['time_runtime_sec'] == 240

        result = store.get_result(jobid)
        assert result['exec_status'] == 'completed'
        assert json.loads(result['json_result']) == {'matches': [1, 2, 3]}

    def test_batch_register_then_status_dict(self, store):
        """Simulate startup: batch register old jobs, then query."""
        entries = [
            {'jobid': f'old_{i}', 'status': 'completed', 'jobcounter': i}
            for i in range(50)
        ]
        store.register_batch(entries)

        # Now add a new job with full metadata
        store.store_metadata('new_1', _make_metadata(jobcounter=51))
        store.update_status('new_1', 'completed')

        result = store.get_job_status_dict(limit=5)
        assert len(result) == 5
        # new_1 should be in the result (highest counter)
        assert 'new_1' in result
        assert result['new_1']['action'] == 'query_chips_simple_dict'
