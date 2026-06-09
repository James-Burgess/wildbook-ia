ARG WBIA_FINAL_IMAGE=wildme/wbia:latest

FROM ${WBIA_FINAL_IMAGE} as org.wildme.wbia.latest

COPY ./ /wbia/wildbook-ia

ENV SETUPTOOLS_SCM_PRETEND_VERSION=5.1.3

RUN /bin/bash -xc '. /virtualenv/env3/bin/activate \
 && pip uninstall -y wildbook-ia \
 && cd /wbia/wildbook-ia \
 && pip install --no-cache-dir -r requirements/runtime.txt \
 && pip install --no-cache-dir -r requirements/postgres.txt \
 && pip install --no-cache-dir -r requirements/tests.txt \
 && pip install --no-cache-dir .'

# Temporary fix for ARM64
ENV LD_PRELOAD "/virtualenv/env3/lib/python3.10/site-packages/torch/lib/libgomp-d22c30c5.so.1"

RUN set -ex \

 && /virtualenv/env3/bin/python -c "import wbia; from wbia.__main__ import smoke_test; smoke_test()"

# Undo Fix
ENV LD_PRELOAD ""

 # Update locate database
RUN updatedb
