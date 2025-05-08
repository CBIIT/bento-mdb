import os
PORT = os.environ.get('STS_PORT') or 5000
bind = f"0.0.0.0:{PORT}"
wsgi_app = "bento_sts.sts:create_app()"
pidfile = "/app/sts.pid"
errorlog = os.environ.get('STS_ERR_LOG') and f"/app/{os.environ['STS_ERR_LOG']}" or "-"
accesslog = os.environ.get('STS_ACC_LOG') and f"/app/{os.environ['STS_ACC_LOG']}" or "-"
loglevel = os.environ.get('STS_LOGLEVEL') or "info"
workers = os.environ.get('STS_WORKERS') or 2
