# -*- coding: utf-8 -*-
"""SQLite WAL-mode job store for the WBIA job engine.

Replaces the per-job shelve files + GLOBAL_SHELVE_LOCK + lock-file
machinery with a single ``jobs.db`` database.  Designed for
single-writer (the collector process) but WAL mode allows concurrent
readers, enabling future direct reads from web threads.
"""
import json
import sqlite3


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    jobid               TEXT PRIMARY KEY,
    jobcounter          INTEGER,
    status              TEXT NOT NULL DEFAULT 'received',
    -- metadata fields
    action              TEXT,
    lane                TEXT,
    callback_url        TEXT,
    callback_method     TEXT,
    callback_detailed   INTEGER DEFAULT 0,
    -- request context
    request_json        TEXT,
    -- large blobs
    args_json           TEXT,
    kwargs_json         TEXT,
    -- timestamps
    time_received       TEXT,
    time_started        TEXT,
    time_updated        TEXT,
    time_completed      TEXT,
    time_runtime        TEXT,
    time_turnaround     TEXT,
    time_runtime_sec    REAL,
    time_turnaround_sec REAL,
    -- result
    exec_status         TEXT,
    json_result         TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_jobcounter ON jobs(jobcounter);
CREATE INDEX IF NOT EXISTS idx_jobs_status     ON jobs(status);
"""


class JobStore:
    """SQLite WAL-mode store for job engine data.

    Parameters
    ----------
    db_path : str
        Path to the SQLite database file (e.g. ``shelves/jobs.db``).
    """

    def __init__(self, db_path):
        self.db_path = db_path
        self._conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            isolation_level='DEFERRED',
        )
        self._conn.execute('PRAGMA journal_mode=WAL')
        self._conn.execute('PRAGMA busy_timeout=5000')
        self._conn.execute('PRAGMA synchronous=NORMAL')
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    #  Write methods (called by collector)
    # ------------------------------------------------------------------

    def store_metadata(self, jobid, metadata):
        """Write full metadata dict for a job (INSERT OR REPLACE)."""
        times = metadata.get('times', {})
        request = metadata.get('request', {})
        if request is None:
            request = {}

        self._conn.execute(
            """INSERT INTO jobs (
                   jobid, jobcounter, action, lane,
                   callback_url, callback_method, callback_detailed,
                   request_json, args_json, kwargs_json,
                   time_received,
                   status
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(jobid) DO UPDATE SET
                   jobcounter=excluded.jobcounter,
                   action=excluded.action,
                   lane=excluded.lane,
                   callback_url=excluded.callback_url,
                   callback_method=excluded.callback_method,
                   callback_detailed=excluded.callback_detailed,
                   request_json=excluded.request_json,
                   args_json=excluded.args_json,
                   kwargs_json=excluded.kwargs_json,
                   time_received=excluded.time_received
            """,
            (
                jobid,
                metadata.get('jobcounter'),
                metadata.get('action'),
                metadata.get('lane'),
                metadata.get('callback_url'),
                metadata.get('callback_method'),
                int(bool(metadata.get('callback_detailed', False))),
                _dumps(request),
                _dumps(metadata.get('args')),
                _dumps(metadata.get('kwargs')),
                times.get('received'),
                'received',
            ),
        )
        self._conn.commit()

    def update_status(self, jobid, status):
        """Update the status column for a job."""
        self._conn.execute(
            'UPDATE jobs SET status=? WHERE jobid=?',
            (status, jobid),
        )
        self._conn.commit()

    def update_times(self, jobid, times):
        """Update timestamp columns from a times dict."""
        self._conn.execute(
            """UPDATE jobs SET
                   time_received=COALESCE(?, time_received),
                   time_started=COALESCE(?, time_started),
                   time_updated=?,
                   time_completed=COALESCE(?, time_completed),
                   time_runtime=COALESCE(?, time_runtime),
                   time_turnaround=COALESCE(?, time_turnaround),
                   time_runtime_sec=COALESCE(?, time_runtime_sec),
                   time_turnaround_sec=COALESCE(?, time_turnaround_sec)
               WHERE jobid=?
            """,
            (
                times.get('received'),
                times.get('started'),
                times.get('updated'),
                times.get('completed'),
                times.get('runtime'),
                times.get('turnaround'),
                times.get('runtime_sec'),
                times.get('turnaround_sec'),
                jobid,
            ),
        )
        self._conn.commit()

    def store_result(self, jobid, engine_result):
        """Store execution result for a completed job."""
        self._conn.execute(
            'UPDATE jobs SET exec_status=?, json_result=? WHERE jobid=?',
            (
                engine_result.get('exec_status'),
                engine_result.get('json_result'),
                jobid,
            ),
        )
        self._conn.commit()

    def ensure_job(self, jobid, status=None):
        """Ensure a row exists for *jobid*.  Does not overwrite existing rows."""
        self._conn.execute(
            'INSERT OR IGNORE INTO jobs (jobid, status) VALUES (?, ?)',
            (jobid, status or 'received'),
        )
        self._conn.commit()

    def register_job(self, jobid, status, jobcounter):
        """Register a job with minimal info (startup recovery / single)."""
        self._conn.execute(
            """INSERT INTO jobs (jobid, status, jobcounter)
               VALUES (?, ?, ?)
               ON CONFLICT(jobid) DO UPDATE SET
                   status=excluded.status,
                   jobcounter=excluded.jobcounter
            """,
            (jobid, status, jobcounter),
        )
        self._conn.commit()

    def register_batch(self, job_entries):
        """Batch-register jobs in a single transaction.

        Parameters
        ----------
        job_entries : list of dict
            Each dict has keys ``jobid``, ``status``, ``jobcounter``.
        """
        with self._conn:
            self._conn.executemany(
                """INSERT INTO jobs (jobid, status, jobcounter)
                   VALUES (?, ?, ?)
                   ON CONFLICT(jobid) DO UPDATE SET
                       status=excluded.status,
                       jobcounter=excluded.jobcounter
                """,
                [
                    (e['jobid'], e['status'], e.get('jobcounter', -1))
                    for e in job_entries
                ],
            )

    def delete_job(self, jobid):
        """Delete a single job row."""
        self._conn.execute('DELETE FROM jobs WHERE jobid=?', (jobid,))
        self._conn.commit()

    def delete_jobs(self, jobid_list):
        """Batch-delete job rows in a single transaction."""
        with self._conn:
            self._conn.executemany(
                'DELETE FROM jobs WHERE jobid=?',
                [(jid,) for jid in jobid_list],
            )

    def vacuum(self):
        """Reclaim disk space after bulk deletes."""
        self._conn.execute('VACUUM')

    # ------------------------------------------------------------------
    #  Read methods
    # ------------------------------------------------------------------

    def get_status(self, jobid):
        """Return the status string for *jobid*, or None."""
        row = self._conn.execute(
            'SELECT status FROM jobs WHERE jobid=?', (jobid,)
        ).fetchone()
        return row[0] if row else None

    def get_job_ids(self):
        """Return all job IDs sorted by jobcounter."""
        rows = self._conn.execute(
            'SELECT jobid FROM jobs ORDER BY jobcounter'
        ).fetchall()
        return [r[0] for r in rows]

    def get_job_status_dict(self, limit=0):
        """Return ``{jobid: {status, jobcounter, action, ...}}`` for display.

        Excludes large blob columns (args, kwargs, json_result).
        When *limit* > 0, returns only the *limit* most recent jobs.
        """
        if limit > 0:
            rows = self._conn.execute(
                """SELECT jobid, jobcounter, status, action, lane,
                          time_received, time_started, time_updated,
                          time_completed, time_runtime, time_turnaround,
                          time_runtime_sec, time_turnaround_sec,
                          request_json
                   FROM jobs
                   ORDER BY jobcounter DESC
                   LIMIT ?
                """,
                (limit,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT jobid, jobcounter, status, action, lane,
                          time_received, time_started, time_updated,
                          time_completed, time_runtime, time_turnaround,
                          time_runtime_sec, time_turnaround_sec,
                          request_json
                   FROM jobs
                   ORDER BY jobcounter DESC
                """
            ).fetchall()

        result = {}
        for row in rows:
            req = _loads(row[13])
            result[row[0]] = {
                'status': row[2],
                'jobcounter': row[1] if row[1] is not None else -1,
                'action': row[3],
                'endpoint': req.get('endpoint') if req else None,
                'function': req.get('function') if req else None,
                'time_received': row[5],
                'time_started': row[6],
                'time_runtime': row[9],
                'time_updated': row[7],
                'time_completed': row[8],
                'time_turnaround': row[10],
                'time_runtime_sec': row[11],
                'time_turnaround_sec': row[12],
                'lane': row[4],
            }
        return result

    def get_metadata(self, jobid):
        """Reconstruct the full metadata dict for one job.

        Returns None if the job doesn't exist or has no metadata stored.
        """
        row = self._conn.execute(
            """SELECT jobcounter, action, lane,
                      callback_url, callback_method, callback_detailed,
                      request_json, args_json, kwargs_json,
                      time_received, time_started, time_updated,
                      time_completed, time_runtime, time_turnaround,
                      time_runtime_sec, time_turnaround_sec
               FROM jobs WHERE jobid=?
            """,
            (jobid,),
        ).fetchone()
        if row is None:
            return None
        # A row with only jobid/status/jobcounter (from register_batch)
        # won't have action set — treat as "no metadata yet" when action
        # is None and no times are set.
        if row[1] is None and row[9] is None:
            return None
        return {
            'jobcounter': row[0],
            'action': row[1],
            'lane': row[2],
            'callback_url': row[3],
            'callback_method': row[4],
            'callback_detailed': bool(row[5]) if row[5] is not None else False,
            'request': _loads(row[6]),
            'args': _loads(row[7]),
            'kwargs': _loads(row[8]),
            'times': {
                'received': row[9],
                'started': row[10],
                'updated': row[11],
                'completed': row[12],
                'runtime': row[13],
                'turnaround': row[14],
                'runtime_sec': row[15],
                'turnaround_sec': row[16],
            },
        }

    def get_times(self, jobid):
        """Return just the times dict for a job, or empty dict."""
        row = self._conn.execute(
            """SELECT time_received, time_started, time_updated,
                      time_completed, time_runtime, time_turnaround,
                      time_runtime_sec, time_turnaround_sec
               FROM jobs WHERE jobid=?
            """,
            (jobid,),
        ).fetchone()
        if row is None:
            return {}
        return {
            'received': row[0],
            'started': row[1],
            'updated': row[2],
            'completed': row[3],
            'runtime': row[4],
            'turnaround': row[5],
            'runtime_sec': row[6],
            'turnaround_sec': row[7],
        }

    def get_result(self, jobid):
        """Return ``{exec_status, json_result, jobid}`` or None."""
        row = self._conn.execute(
            'SELECT exec_status, json_result FROM jobs WHERE jobid=?',
            (jobid,),
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return {
            'exec_status': row[0],
            'json_result': row[1],
            'jobid': jobid,
        }

    def get_callback_info(self, jobid):
        """Return callback_url, callback_method, callback_detailed or Nones."""
        row = self._conn.execute(
            'SELECT callback_url, callback_method, callback_detailed FROM jobs WHERE jobid=?',
            (jobid,),
        ).fetchone()
        if row is None:
            return None, None, False
        return row[0], row[1], bool(row[2]) if row[2] is not None else False

    def get_max_jobcounter(self):
        """Return the maximum jobcounter, or 0."""
        row = self._conn.execute('SELECT MAX(jobcounter) FROM jobs').fetchone()
        return row[0] if row and row[0] is not None else 0

    def job_exists(self, jobid):
        """Check if a job row exists."""
        row = self._conn.execute(
            'SELECT 1 FROM jobs WHERE jobid=? LIMIT 1', (jobid,)
        ).fetchone()
        return row is not None


def _dumps(obj):
    """JSON-serialize, returning None for None."""
    if obj is None:
        return None
    return json.dumps(obj)


def _loads(s):
    """JSON-deserialize, returning None for None."""
    if s is None:
        return None
    return json.loads(s)
