# -*- coding: utf-8 -*-
import logging

import utool as ut
from prometheus_client import Counter, Enum, Gauge, Histogram, Info  # NOQA

import wbia.constants as const
from wbia.control import controller_inject
from wbia.web.apis_query import RENDER_STATUS  # NOQA

(print, rrr, profile) = ut.inject2(__name__)
logger = logging.getLogger('wbia')

CLASS_INJECT_KEY, register_ibs_method = controller_inject.make_ibs_register_decorator(
    __name__
)
register_api = controller_inject.get_wbia_flask_api(__name__)


PROMETHEUS_COUNTER = 0
PROMETHEUS_LIMIT = 30  # kept for prometheus_update() backward compat

import threading as _threading
_PROMETHEUS_BUSY = False
_PROMETHEUS_BUSY_LOCK = _threading.Lock()

# Interval (seconds) for the standalone background refresh timer.
_PROMETHEUS_REFRESH_INTERVAL = 60


PROMETHEUS_DATA = {
    'info': Info(
        'wbia_db',
        'Description of WBIA database',
    ),
    'update': Gauge(
        'wbia_update_seconds',
        'Number of seconds for the most recent Prometheus update',
        ['name'],
    ),
    'imagesets': Gauge(
        'wbia_assets_imagesets',
        'Number of imagesets in WBIA database',
        ['name'],
    ),
    'images': Gauge(
        'wbia_assets_images',
        'Number of images in WBIA database',
        ['name'],
    ),
    'annotations': Gauge(
        'wbia_assets_annotations',
        'Number of annotations in WBIA database',
        ['name'],
    ),
    'parts': Gauge(
        'wbia_assets_parts',
        'Number of parts in WBIA database',
        ['name'],
    ),
    'names': Gauge(
        'wbia_assets_names',
        'Number of names in WBIA database',
        ['name'],
    ),
    'species': Gauge(
        'wbia_assets_species',
        'Number of species in WBIA database',
        ['name'],
    ),
    'renders': Gauge(
        'wbia_assets_renders',
        'Number of rendered images in WBIA database',
        ['name', 'status'],
    ),
    'engine': Gauge(
        'wbia_engine_jobs',
        'Job engine status',
        ['name', 'status', 'endpoint'],
    ),
    'process': Gauge(
        'wbia_engine_dead_process',
        'Job engine status',
        ['name', 'process'],
    ),
    'runtime': Gauge(
        'wbia_runtime_seconds',
        'Number of runtime seconds for the current working job',
        ['name', 'endpoint'],
    ),
    'turnaround': Gauge(
        'wbia_turnaround_seconds',
        'Number of turnaround seconds for the current working job',
        ['name', 'endpoint'],
    ),
    'api': Counter(
        'wbia_api_counter',
        'Number of calls per WBIA API',
        ['name', 'tag'],
    ),
    'route': Counter(
        'wbia_route_counter',
        'Number of calls per WBIA route endpoint',
        ['name', 'tag'],
    ),
    'exception': Counter(
        'wbia_exception_counter',
        'Number of web exceptions',
        ['name', 'tag'],
    ),
}


PROMETHUS_JOB_CACHE_DICT = {}


@register_ibs_method
def prometheus_increment_api(ibs, tag):
    try:
        if ibs.containerized:
            container_name = const.CONTAINER_NAME
        else:
            container_name = ibs.dbname

        PROMETHEUS_DATA['api'].labels(name=container_name, tag=tag).inc()
    except Exception:
        pass


@register_ibs_method
def prometheus_increment_route(ibs, tag):
    try:
        if ibs.containerized:
            container_name = const.CONTAINER_NAME
        else:
            container_name = ibs.dbname

        PROMETHEUS_DATA['route'].labels(name=container_name, tag=tag).inc()
    except Exception:
        pass


@register_ibs_method
def prometheus_increment_exception(ibs, tag):
    try:
        if ibs.containerized:
            container_name = const.CONTAINER_NAME
        else:
            container_name = ibs.dbname

        PROMETHEUS_DATA['exception'].labels(name=container_name, tag=tag).inc()
    except Exception:
        pass


@register_ibs_method
@register_api(
    '/api/test/prometheus/',
    methods=['GET', 'POST', 'DELETE', 'PUT'],
    __api_plural_check__=False,
)
def prometheus_update(ibs, *args, **kwargs):
    global _PROMETHEUS_BUSY
    try:
        with ut.Timer(verbose=False) as timer:
            if ibs.containerized:
                container_name = const.CONTAINER_NAME
            else:
                container_name = ibs.dbname

            global PROMETHEUS_COUNTER

            global RENDER_STATUS

            if RENDER_STATUS is None:
                RENDER_STATUS = ibs._init_render_status()

            PROMETHEUS_COUNTER = PROMETHEUS_COUNTER + 1  # NOQA

            if PROMETHEUS_COUNTER >= PROMETHEUS_LIMIT:
                PROMETHEUS_COUNTER = 0

                # Run the expensive refresh in a background thread so the
                # heartbeat response is never blocked by ZMQ/DB calls.
                # Skip if a previous refresh is still running.
                with _PROMETHEUS_BUSY_LOCK:
                    if _PROMETHEUS_BUSY:
                        return
                    _PROMETHEUS_BUSY = True

                def _bg_refresh():
                    global _PROMETHEUS_BUSY
                    try:
                        _prometheus_refresh(ibs, container_name)
                    finally:
                        _PROMETHEUS_BUSY = False

                _t = _threading.Thread(target=_bg_refresh, daemon=True)
                _t.start()
        try:
            PROMETHEUS_DATA['update'].labels(name=container_name).set(timer.ellapsed)
        except Exception:
            pass
    except Exception:
        pass


def _prometheus_refresh(ibs, container_name):
    """The expensive part of prometheus — DB queries + ZMQ calls.

    Separated from prometheus_update so that the heartbeat counter
    logic stays lightweight and concurrent heartbeats don't pile up.
    """
    global RENDER_STATUS

    try:
        PROMETHEUS_DATA['info'].info(
            {
                'uuid': str(ibs.get_db_init_uuid()),
                'dbname': ibs.dbname,
                'hostname': ut.get_computer_name(),
                'container': container_name,
                'version': ibs.db.get_db_version(),
                'containerized': str(int(ibs.containerized)),
                'production': str(int(ibs.production)),
            }
        )
    except Exception:
        pass

    try:
        if ibs.production:
            num_imageset_rowids = 0
            num_gids = 0
            num_aids = 0
            num_pids = 0
            num_nids = 0
            num_species = 0
        else:
            num_imageset_rowids = len(ibs._get_all_imageset_rowids())
            num_gids = len(ibs._get_all_gids())
            num_aids = len(ibs._get_all_aids())
            num_pids = len(ibs._get_all_part_rowids())
            num_nids = len(ibs._get_all_name_rowids())
            num_species = len(ibs._get_all_species_rowids())

        PROMETHEUS_DATA['imagesets'].labels(name=container_name).set(
            num_imageset_rowids
        )
        PROMETHEUS_DATA['images'].labels(name=container_name).set(num_gids)
        PROMETHEUS_DATA['annotations'].labels(name=container_name).set(num_aids)
        PROMETHEUS_DATA['parts'].labels(name=container_name).set(num_pids)
        PROMETHEUS_DATA['names'].labels(name=container_name).set(num_nids)
        PROMETHEUS_DATA['species'].labels(name=container_name).set(num_species)
    except Exception:
        logger.exception('[prometheus] Failed to update asset gauges')

    # ---- Job engine status counts (full, not capped) ----
    status_dict_template = {
        'received': 0,
        'accepted': 0,
        'queued': 0,
        'working': 0,
        'publishing': 0,
        'completed': 0,
        'exception': 0,
        'suppressed': 0,
        'corrupted': 0,
        '_error': 0,
    }
    status_dict = {
        '*': status_dict_template.copy(),
    }
    endpoints = set()

    try:
        # Use lightweight GROUP BY query — never loads individual rows.
        from os.path import join as _join

        from wbia.web.job_store import JobStore

        _shelve_path = ibs.get_shelves_path()
        _db_path = _join(_shelve_path, 'jobs.db')
        _store = JobStore(_db_path)
        try:
            status_counts = _store.get_status_counts()
            active_jobs = _store.get_active_jobs()
        finally:
            _store.close()
    except Exception:
        logger.exception('[prometheus] Failed to read job status from SQLite')
        status_counts = {}
        active_jobs = []

    # Build per-endpoint and aggregate counts
    for (status, endpoint), count in status_counts.items():
        if status not in status_dict_template:
            status = '_error'
        if endpoint not in status_dict:
            status_dict[endpoint] = status_dict_template.copy()
        endpoints.add(endpoint)
        status_dict[endpoint][status] += count
        status_dict['*'][status] += count

    # Timing metrics from recently completed jobs
    try:
        for job in active_jobs:
            if job['status'] == 'working':
                continue
            endpoint = job.get('endpoint', 'None')
            runtime_sec = job.get('time_runtime_sec')
            if runtime_sec is not None:
                PROMETHEUS_DATA['runtime'].labels(
                    name=container_name, endpoint=endpoint
                ).set(runtime_sec)
                PROMETHEUS_DATA['runtime'].labels(
                    name=container_name, endpoint='*'
                ).set(runtime_sec)
            turnaround_sec = job.get('time_turnaround_sec')
            if turnaround_sec is not None:
                PROMETHEUS_DATA['turnaround'].labels(
                    name=container_name, endpoint=endpoint
                ).set(turnaround_sec)
                PROMETHEUS_DATA['turnaround'].labels(
                    name=container_name, endpoint='*'
                ).set(turnaround_sec)
    except Exception:
        logger.exception('[prometheus] Failed to update job timing gauges')

    try:
        for endpoint in status_dict:
            for status in status_dict[endpoint]:
                number = status_dict[endpoint][status]
                PROMETHEUS_DATA['engine'].labels(
                    status=status, name=container_name, endpoint=endpoint
                ).set(number)
    except Exception:
        logger.exception('[prometheus] Failed to update engine job gauges')

    try:
        for status in RENDER_STATUS:
            number = RENDER_STATUS[status]
            PROMETHEUS_DATA['renders'].labels(
                status=status, name=container_name
            ).set(number)
    except Exception:
        pass

    try:
        process_status_dict = ibs.get_process_alive_status()
        for process in process_status_dict:
            number = 0 if process_status_dict.get(process, False) else 1
            PROMETHEUS_DATA['process'].labels(
                process=process, name=container_name
            ).set(number)
    except Exception:
        logger.exception('[prometheus] Failed to update process status gauges')


_PROMETHEUS_TIMER = None


def start_prometheus_timer(ibs):
    """Start a background daemon thread that refreshes Prometheus metrics
    every _PROMETHEUS_REFRESH_INTERVAL seconds.  Called once at app startup.

    This replaces the old approach of piggybacking on /api/test/heartbeat/,
    which caused thread-pool exhaustion when the collector was slow.
    """
    global _PROMETHEUS_TIMER

    if _PROMETHEUS_TIMER is not None:
        return  # already running

    if ibs.containerized:
        container_name = const.CONTAINER_NAME
    else:
        container_name = ibs.dbname

    def _loop():
        global RENDER_STATUS
        while True:
            try:
                if RENDER_STATUS is None:
                    RENDER_STATUS = ibs._init_render_status()
                _prometheus_refresh(ibs, container_name)
            except Exception:
                logger.exception('[prometheus] Background refresh failed')
            _threading.Event().wait(_PROMETHEUS_REFRESH_INTERVAL)

    _PROMETHEUS_TIMER = _threading.Thread(target=_loop, daemon=True, name='prometheus-refresh')
    _PROMETHEUS_TIMER.start()
    logger.info('[prometheus] Background refresh timer started (interval=%ds)',
                _PROMETHEUS_REFRESH_INTERVAL)
