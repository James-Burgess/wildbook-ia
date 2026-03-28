FROM nvidia/cuda:13.0.1-cudnn-runtime-ubuntu24.04

LABEL maintainer="Wild Me <dev@wildme.org>"
LABEL description="Wildbook IA - Simplified single-stage build"

# Environment setup
ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8
ENV DISPLAY=:1
ENV DEBIAN_FRONTEND=noninteractive

# Create working directories
WORKDIR /wbia
RUN mkdir -p /data/db /cache

# Fix for Arm64 builds and basic system setup
# RUN set -ex \
#   && ln -s /usr/bin/dpkg-split /usr/sbin/dpkg-split \
#   && ln -s /usr/bin/dpkg-deb /usr/sbin/dpkg-deb \
#   && ln -s /bin/rm /usr/sbin/rm \
#   && ln -s /bin/tar /usr/sbin/tar \
#   && apt-key adv --fetch-keys https://developer.download.nvidia.com/compute/cuda/repos/ubuntu1804/x86_64/3bf863cc.pub \
#   && apt-get update \
#   && apt-get install -y --no-install-recommends \
#   software-properties-common \
#   apt-utils \
#   && add-apt-repository ppa:deadsnakes/ppa \
#   && apt-get upgrade -y

# Install system dependencies in one layer
RUN apt-get update && apt-get install -y --no-install-recommends \
  # Build essentials
  ca-certificates \
  build-essential \
  lsb-release \
  pkg-config \
  cmake \
  ninja-build \
  git \
  curl \
  # Python 3.12 (default in Ubuntu 24.04)
  python3 \
  python3-dev \
  python3-pip \
  python3-setuptools \
  python3-venv \
  # OpenCV and ML dependencies
  libopencv-dev \
  libboost-all-dev \
  libeigen3-dev \
  libatlas-base-dev \
  liblapack-dev \
  libblas-dev \
  libhdf5-dev \
  liblz4-dev \
  # Qt and GUI
  qtbase5-dev \
  qtchooser \
  qt5-qmake \
  qtbase5-dev-tools \
  # X11 and display
  xvfb \
  x11-utils \
  # Cleanup in same layer
  && apt-get clean \
  && apt-get autoclean \
  && apt-get autoremove -y \
  && rm -rf /var/cache/apt /var/lib/apt/lists/*

# Create virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip and install core packages in venv
RUN pip install --no-cache-dir --upgrade \
  pip \
  setuptools \
  wheel \
  setuptools_scm

# Install Rust (required for some Python packages)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Copy source code (this should be the ONLY copy operation)
COPY . /wbia/wildbook-ia/

# Install minimal dependencies to avoid conflicts
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# WBIA Toolkits
RUN pip install wbia-utool
RUN pip install wbia-pyflann
RUN pip install wbia-vtool

WORKDIR /wbia/
# # Clone essential plugins only (not all 15+)
# RUN set -ex \
#  && cd /wbia \
#  && git clone --depth=3 --recursive https://github.com/WildMeOrg/wbia-plugin-cnn.git \
#  && git clone --depth=3 https://github.com/WildMeOrg/wbia-plugin-orientation.git \
#  && git clone --depth=3 https://github.com/WildMeOrg/wbia-plugin-deepsense.git
#
# # Install essential plugins
# RUN set -ex \
#  && cd /wbia/wbia-plugin-cnn && bash run_developer_setup.sh \
#  && cd /wbia/wbia-plugin-orientation && python3.7 -m pip install --no-cache-dir -e . \
#  && cd /wbia/wbia-plugin-deepsense && python3.7 -m pip install --no-cache-dir -e .
#
# Install main WBIA package
RUN set -ex \
  && cd /wbia/wildbook-ia \
  && pip install --no-cache-dir -e .

# Create minimal entrypoint script
RUN echo '#!/bin/bash\n\
  cd /wbia/wildbook-ia\n\
  exec python -m wbia.dev --dbdir /data/db --web --containerized "$@"' > /bin/entrypoint \
  && chmod +x /bin/entrypoint

# Set up data directory
VOLUME ["/data/db", "/cache"]
WORKDIR /data/db

# Expose web port
EXPOSE 5000

# Default entrypoint
ENTRYPOINT ["/bin/entrypoint"]
CMD []
