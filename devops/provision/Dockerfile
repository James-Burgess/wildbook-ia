ARG WBIA_BASE_IMAGE=wildme/wbia-base:latest

FROM ${WBIA_BASE_IMAGE} as org.wildme.wbia.provision

# Wildbook IA version
ARG VCS_URL="https://github.com/WildMeOrg/wildbook-ia"

ARG VCS_REF="main"

# Clone WBIA repository
RUN set -ex \
 && cd /wbia \
 && git clone --branch ${VCS_REF} ${VCS_URL}

# Clone WBIA toolkit repositories
RUN set -ex \
 && cd /wbia \
 && git clone https://github.com/WildMeOrg/wbia-utool.git \
 && git clone https://github.com/WildMeOrg/wbia-vtool.git

# Clone WBIA third-party toolkit repositories
RUN set -ex \
 && cd /wbia \
 && git clone https://github.com/WildMeOrg/wbia-tpl-pyhesaff.git \
 && git clone https://github.com/WildMeOrg/wbia-tpl-pyflann.git \
 && git clone https://github.com/WildMeOrg/wbia-tpl-pydarknet.git \
 # Depricated
 && git clone https://github.com/WildMeOrg/wbia-deprecate-tpl-brambox.git \
 && git clone https://github.com/WildMeOrg/wbia-deprecate-tpl-lightnet.git

# Clone first-party WBIA plug-in repositories
RUN set -ex \
 && cd /wbia \
 && git clone https://github.com/WildMeOrg/wbia-plugin-orientation.git \
 && git clone https://github.com/WildMeOrg/wbia-plugin-pie-v2.git \
 && git clone --recurse-submodules https://github.com/WildMeOrg/wbia-plugin-miew-id.git

# Clone upstream LightGlue, then LightGlue and Hybrid plug-in repositories
RUN set -ex \
 && cd /wbia \
 && git clone https://github.com/cvg/LightGlue.git \
 && git clone https://github.com/WildMeOrg/wbia-plugin-lightglue.git \
 && git clone --recursive https://github.com/WildMeOrg/wbia-plugin-hybrid.git \
 && cd /wbia/wbia-plugin-hybrid/wbia_hybrid \
 && git fetch origin \
 && git checkout main

# Deprecated/removed plugins: kaggle7, deepsense, whaleridgefindr, finfindr, curvrank, pie (v1), blend, lca

# Upgrade pip, setuptools and wheel before installing any packages
# Upgrade pip/setuptools/wheel.  Pin setuptools<75 because 75+ drops pkg_resources
# from build-isolation overlays, breaking legacy packages (brambox, visdom, etc.).
RUN /bin/bash -xc '. /virtualenv/env3/bin/activate \
 && pip install --upgrade "pip>=23,<26" "setuptools>=69,<75" wheel'

# Constrain setuptools in ALL pip build-isolation environments so that
# transitive dependencies also get a setuptools with working pkg_resources.
RUN echo "setuptools<75" > /tmp/pip-constraints.txt
ENV PIP_CONSTRAINT=/tmp/pip-constraints.txt

# Install PyTorch with CUDA early so subsequent pip installs find it satisfied
# (avoids downloading CPU-only torch multiple times then replacing it later)
RUN /bin/bash -xc '. /virtualenv/env3/bin/activate \
 && pip install --no-cache-dir \
     torch==2.0.1 \
     torchvision==0.15.2 \
     torchaudio==2.0.2 \
     --extra-index-url https://download.pytorch.org/whl/cu117'

# WBIA Toolkits
RUN set -ex \
 && /bin/bash -xc '. /virtualenv/env3/bin/activate \
 && cd /wbia/wbia-utool \
 && /bin/bash run_developer_setup.sh'

RUN set -ex \
 && /bin/bash -xc '. /virtualenv/env3/bin/activate \
 && cd /wbia/wbia-vtool \
 && /bin/bash run_developer_setup.sh'

# WBIA third-party toolkits
RUN set -ex \
 && /bin/bash -xc '. /virtualenv/env3/bin/activate \
 && cd /wbia/wbia-tpl-pyhesaff \
 && /bin/bash run_developer_setup.sh'

RUN set -ex \
 && /bin/bash -xc '. /virtualenv/env3/bin/activate \
 && cd /wbia/wbia-tpl-pyflann \
 && /bin/bash run_developer_setup.sh'

RUN set -ex \
 && /bin/bash -xc '. /virtualenv/env3/bin/activate \
 && cd /wbia/wbia-tpl-pydarknet \
 && /bin/bash run_developer_setup.sh'


RUN /bin/bash -xc '. /virtualenv/env3/bin/activate \
 && cd /wbia/wbia-deprecate-tpl-brambox \
 && pip install --no-build-isolation --no-cache-dir -e .'

RUN /bin/bash -xc '. /virtualenv/env3/bin/activate \
 && cd /wbia/wbia-deprecate-tpl-lightnet \
 && pip install --no-build-isolation --no-cache-dir -e .'


# Install Rust non-interactively (required for timm library used in WBIA)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
# Add Rust to PATH globally
ENV PATH="/root/.cargo/bin:${PATH}"

# Wildbook IA
# Note: run_developer_setup.sh uses editable install (pip install -e .) which
# requires PEP 660 support that scikit-build lacks.  For Docker we install
# requirements then do a regular (non-editable) install instead.
RUN /bin/bash -xc '. /virtualenv/env3/bin/activate \
 && cd /wbia/wildbook-ia \
 && pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir . \
 && pip install --no-cache-dir -r requirements/postgres.txt'

# WBIA third-party plug-ins
# CNN plugin removed (depends on theano/lasagne, incompatible with Python 3.10+)
RUN /bin/bash -xc '. /virtualenv/env3/bin/activate \
 && cd /wbia/wbia-plugin-pie-v2 \
 && /bin/bash run_developer_setup.sh'

# Deprecated/removed plugin installs: finfindr, whaleridgefindr, deepsense, kaggle7, blend, lca

RUN /bin/bash -xc '. /virtualenv/env3/bin/activate \
 && cd /wbia/wbia-plugin-orientation \
 && pip install --no-cache-dir .'

RUN /bin/bash -xc '. /virtualenv/env3/bin/activate \
 && cd /wbia/LightGlue \
 && pip install --no-cache-dir . \
 && cd /wbia/wbia-plugin-lightglue \
 && pip install --no-cache-dir .'

RUN /bin/bash -xc '. /virtualenv/env3/bin/activate \
 && cd /wbia/wbia-plugin-hybrid \
 && pip install --no-cache-dir .'

# pairx submodule lacks __init__.py files needed by find_packages()
RUN find /wbia/wbia-plugin-miew-id/wbia_miew_id -type d \
    ! -path '*__pycache__*' ! -path '*.git*' \
    ! -exec test -f '{}/__init__.py' \; \
    -exec sh -c 'echo "# -*- coding: utf-8 -*-" > "{}/__init__.py"' \;

RUN /bin/bash -xc '. /virtualenv/env3/bin/activate \
 && cd /wbia/wbia-plugin-miew-id \
 && pip install --no-cache-dir timm grad-cam optuna zennit python-dotenv albumentations \
 && pip install --no-cache-dir .'

# Clean up old/conflicting packages (torch already installed early with CUDA)
RUN /virtualenv/env3/bin/pip uninstall -y \
     dtool-ibeis guitool-ibeis plottool-ibeis utool-ibeis vtool-ibeis \
     dtool guitool plottool utool vtool \
     lightnet brambox \
     opencv-python opencv-contrib-python \
     opencv-python-headless opencv-contrib-python-headless \
 ; /virtualenv/env3/bin/pip install --no-cache-dir \
     pynvml \
     opencv-contrib-python-headless

# Wildbook IA problematic dependencies
RUN /bin/bash -xc '. /virtualenv/env3/bin/activate \
 && cd /wbia/wildbook-ia \
 && pip install --no-cache-dir -r requirements/problematic.txt'

# Ensure that we are running the local installed copy, not from PyPI
RUN set -ex \
 && /virtualenv/env3/bin/pip uninstall -y \
     wildbook-ia \
 && cd /wbia/wildbook-ia \
 && /virtualenv/env3/bin/pip install --no-cache-dir .