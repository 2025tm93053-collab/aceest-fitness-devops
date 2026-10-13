# syntax=docker/dockerfile:1
#
# Stages:  base -> test      (docker build --target test)     pytest + flake8 live here
#          base -> runtime   (default; last stage)             production image
#
# `docker build .` therefore produces the lean runtime image, while
# `docker build --target test .` produces the image CI uses to run pytest.

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt


FROM base AS test
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
COPY app.py db.py services.py pytest.ini .flake8 ./
COPY templates/ templates/
COPY static/ static/
COPY tests/ tests/
CMD ["pytest", "-q"]


FROM base AS runtime
# Non-root user; /data holds the SQLite file and can be mounted as a volume.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin aceest \
    && mkdir /data \
    && chown aceest /data
COPY app.py db.py services.py ./
COPY templates/ templates/
COPY static/ static/
ENV FLASK_APP=app \
    ACEEST_DB_PATH=/data/aceest.db
USER aceest
VOLUME ["/data"]
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=3).status == 200 else 1)"]
# One worker (with threads) so session cookies stay valid without a shared secret store.
# --no-control-socket: the control interface is unused and wants a writable $HOME.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", \
     "--no-control-socket", "--access-logfile", "-", "app:create_app()"]
