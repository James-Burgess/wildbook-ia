# -*- coding: utf-8 -*-
"""
Dependencies: flask, gunicorn
"""
import logging
import os
import socket

import utool as ut

from wbia.control import controller_inject
from wbia.web import apis_engine
from wbia.web import appfuncs as appf
from wbia.web import job_engine

(print, rrr, profile) = ut.inject2(__name__)
logger = logging.getLogger('wbia')


try:
    try:
        from werkzeug.wsgi import DispatcherMiddleware
    except ImportError:
        from werkzeug.middleware.dispatcher import DispatcherMiddleware
    import prometheus_client

    from wbia.web import prometheus  # NOQA

    PROMETHEUS = True
except ImportError:
    PROMETHEUS = False


def _quiet_heartbeat_filter(record):
    """Filter out noisy heartbeat/metrics log lines."""
    msg = record.getMessage()
    quiet_paths = ['/api/test/heartbeat', '/metrics']
    if any(path in msg for path in quiet_paths):
        if '200' in msg or '\"200\"' in msg:
            return False
    return True


def start_web_server(
    ibs, port=None, browser=None, url_suffix=None, start_web_loop=True, fallback=True
):
    """Initialize the web server using Gunicorn (multi-worker, threaded)."""
    if browser is None:
        browser = ut.get_argflag('--browser')
    if url_suffix is None:
        url_suffix = ut.get_argval('--url', default='')

    if port is None:
        port = appf.DEFAULT_WEB_API_PORT

    # Get Flask app
    app = controller_inject.get_flask_app()

    # Database URI for v2 API models (configurable via env var for PostgreSQL, etc.)
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'WBIA_SQLALCHEMY_DATABASE_URI', 'sqlite:///api_v2.sqlite3'
    )
    # SECRET_KEY is already set securely in controller_inject.py via os.urandom(64)

    app.ibs = ibs
    # Try to ascertain the socket's domain name
    socket.setdefaulttimeout(0.1)
    try:
        app.server_domain = socket.gethostbyname(socket.gethostname())
    except socket.gaierror:
        app.server_domain = '127.0.0.1'
    socket.setdefaulttimeout(None)
    app.server_port = port
    app.server_url = 'http://{}:{}'.format(app.server_domain, app.server_port)
    logger.info('[web] Server starting at {}'.format(app.server_url))

    # Initialize all version 2 extensions
    from wbia.web import extensions

    extensions.init_app(app)

    # Initialize all version 2 modules
    from wbia.web import modules

    modules.init_app(app)

    logger.info('Using route rules:')
    for rule in app.url_map.iter_rules():
        logger.info('\t{!r}'.format(rule))

    if browser:
        url = app.server_url + url_suffix
        import webbrowser

        logger.info('[web] opening browser with url = {!r}'.format(url))
        webbrowser.open(url)

    wsgi_app = app
    if PROMETHEUS:
        logger.info('LOADING PROMETHEUS')
        wsgi_app = DispatcherMiddleware(
            app, {'/metrics': prometheus_client.make_wsgi_app()}
        )
        wsgi_app.server_port = app.server_port
        wsgi_app.server_url = app.server_url
        wsgi_app.ibs = app.ibs

        # Prometheus timer is started in the post_fork hook (see below)
        # so it runs in the worker process, not the master.
    else:
        logger.info('SKIPPING PROMETHEUS')

    # Configure logging
    try:
        utool_logfile_handler = ut.util_logging.__UTOOL_ROOT_LOGGER__
    except Exception:
        utool_logfile_handler = None

    if utool_logfile_handler is not None:
        for handler in utool_logfile_handler.handlers:
            if isinstance(handler, ut.CustomStreamHandler):
                utool_logfile_handler.removeHandler(handler)

        logger_list = []
        try:
            logger_list += [app.logger]
        except AttributeError:
            pass
        try:
            logger_list += [app.app.logger]
        except AttributeError:
            pass
        logger_list += [
            logging.getLogger('concurrent'),
            logging.getLogger('concurrent.futures'),
            logging.getLogger('urllib3'),
            logging.getLogger('requests'),
            logging.getLogger('gunicorn'),
            logging.getLogger('gunicorn.access'),
            logging.getLogger('gunicorn.error'),
            logging.getLogger('websocket'),
            logging.getLogger('wbia'),
        ]
        for logger_ in logger_list:
            logger_.setLevel(logging.INFO)
            logger_.addHandler(utool_logfile_handler)

    # Suppress heartbeat/metrics noise from gunicorn access log
    gunicorn_access_logger = logging.getLogger('gunicorn.access')
    gunicorn_access_logger.addFilter(type(
        '_QuietFilter', (), {'filter': staticmethod(_quiet_heartbeat_filter)}
    )())

    logging.basicConfig(level=logging.INFO)

    if start_web_loop:
        # Gunicorn concurrency configuration.
        #
        # IMPORTANT: workers MUST be 1.  The ibs controller, DB connections,
        # and ZMQ job engine state are created before Gunicorn forks.  With
        # >1 workers, each fork would inherit copies of these objects,
        # causing socket corruption, stale DB connections, and duplicate
        # background threads.  All concurrency comes from gthread threads,
        # protected by _engine_lock / _collect_lock in JobInterface.
        num_workers = 1
        num_threads = max(1, int(os.environ.get(
            'WBIA_WEB_THREADS',
            ut.get_argval('--web-threads', int, 16),
        )))

        import gunicorn.app.base

        class WbiaGunicornApp(gunicorn.app.base.BaseApplication):
            """Custom Gunicorn application to run the WBIA Flask app."""

            def __init__(self, application, options=None):
                self.application = application
                self.options = options or {}
                super().__init__()

            def load_config(self):
                for key, value in self.options.items():
                    if key in self.cfg.settings and value is not None:
                        self.cfg.set(key.lower(), value)

            def load(self):
                return self.application

        # Start Prometheus timer in the worker process (post-fork) so
        # gauge updates happen in the same process that serves /metrics.
        def _post_fork(server, worker):
            if PROMETHEUS:
                prometheus.start_prometheus_timer(ibs)

        options = {
            'bind': '0.0.0.0:{}'.format(port),
            'workers': num_workers,
            'threads': num_threads,
            'worker_class': 'gthread',
            'timeout': 3600,
            # preload_app MUST be False.  Gunicorn always forks at least one
            # worker from the master process.  ZMQ contexts/sockets created
            # before fork() (e.g. the global zmq.Context.instance() and any
            # sockets opened during app init) become invalid in the child,
            # causing "Assertion failed: ok (src/mailbox.cpp:99)" crashes.
            'preload_app': False,
            'post_fork': _post_fork,
            'accesslog': '-',
            'errorlog': '-',
            'loglevel': 'info',
        }

        logger.info(
            '[web] Starting Gunicorn with {} worker x {} threads on port {}'.format(
                num_workers, num_threads, port
            )
        )

        try:
            WbiaGunicornApp(wsgi_app, options).run()
        except KeyboardInterrupt:
            logger.info('Caught ctrl+c in webserver. Gracefully exiting')


# Keep old name as alias for compatibility
start_tornado = start_web_server


def start_from_wbia(
    ibs,
    port=None,
    browser=None,
    precache=None,
    url_suffix=None,
    start_job_queue=None,
    start_web_loop=True,
):
    """
    Parse command line options and start the server.

    CommandLine:
        python -m wbia --db PZ_MTEST --web
        python -m wbia --db PZ_MTEST --web --browser
    """
    logger.info('[web] start_from_wbia()')

    if start_job_queue is None:
        if ut.get_argflag('--noengine'):
            start_job_queue = False
        else:
            start_job_queue = True

    if precache is None:
        precache = ut.get_argflag('--precache')

    if precache:
        gid_list = ibs.get_valid_gids()
        logger.info('[web] Pre-computing all image thumbnails (with annots)...')
        ibs.get_image_thumbpath(gid_list, draw_annots=True)
        logger.info('[web] Pre-computing all image thumbnails (without annots)...')
        ibs.get_image_thumbpath(gid_list, draw_annots=False)
        logger.info('[web] Pre-computing all annotation chips...')
        ibs.check_chip_existence()
        ibs.compute_all_chips()

    if start_job_queue:
        logger.info('[web] opening job manager')
        ibs.load_plugin_module(job_engine)
        ibs.load_plugin_module(apis_engine)
        # No need to sleep, this call should block until engine is live.
        ibs.initialize_job_manager()

    logger.info('[web] starting web server')
    try:
        start_web_server(ibs, port, browser, url_suffix, start_web_loop)
    except KeyboardInterrupt:
        logger.info('Caught ctrl+c in webserver. Gracefully exiting')
    if start_web_loop:
        logger.info('[web] closing job manager')
        ibs.close_job_manager()


def start_web_annot_groupreview(ibs, aid_list):
    r"""
    Args:
        ibs (IBEISController):  wbia controller object
        aid_list (list):  list of annotation rowids

    CommandLine:
        python -m wbia.tag_funcs --exec-start_web_annot_groupreview --db PZ_Master1
        python -m wbia.tag_funcs --exec-start_web_annot_groupreview --db GZ_Master1
        python -m wbia.tag_funcs --exec-start_web_annot_groupreview --db GIRM_Master1

    Example:
        >>> # SCRIPT
        >>> from wbia.tag_funcs import *  # NOQA
        >>> import wbia
        >>> #ibs = wbia.opendb(defaultdb='PZ_Master1')
        >>> ibs = wbia.opendb(defaultdb='GZ_Master1')
        >>> #aid_list = ibs.get_valid_aids()
        >>> # -----
        >>> any_tags = ut.get_argval('--tags', type_=list, default=['Viewpoint'])
        >>> min_num = ut.get_argval('--min_num', type_=int, default=1)
        >>> prop = any_tags[0]
        >>> filtered_annotmatch_rowids = filter_annotmatch_by_tags(ibs, None, any_tags=any_tags, min_num=min_num)
        >>> aid1_list = (ibs.get_annotmatch_aid1(filtered_annotmatch_rowids))
        >>> aid2_list = (ibs.get_annotmatch_aid2(filtered_annotmatch_rowids))
        >>> aid_list = list(set(ut.flatten([aid2_list, aid1_list])))
        >>> result = start_web_annot_groupreview(ibs, aid_list)
        >>> print(result)
    """
    import wbia.web

    aid_strs = ','.join(list(map(str, aid_list)))
    url_suffix = '/group_review/?aid_list=%s' % (aid_strs)
    wbia.web.app.start_from_wbia(ibs, url_suffix=url_suffix, browser=True)
