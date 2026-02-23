#!/bin/bash

set -ex

export CUR_LOC="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
pip install git+https://github.com/WildMeOrg/wbia-utool.git
pip install wbia-pyhesaff
pip install -r requirements/build.txt
pip install --upgrade pip
pip install setuptools wheel setuptools_scm scikit-build cmake ninja

pip install --upgrade setuptools wheel setuptools_scm

# Use --use-pep517 for modern PEP-compatible builds
pip install --use-pep517 git+https://github.com/WildMeOrg/wbia-utool.git
pip install --use-pep517 git+https://github.com/WildMeOrg/wbia-vtool.git
pip install --use-pep517 git+https://github.com/WildMeOrg/wbia-pyhesaff.git

if command -v yum &> /dev/null
then
    yum install -y \
        epel-release \
        yum-utils

    yum-config-manager --enable pgdg12

    yum install -y \
        geos-devel \
        gdal-devel \
        proj-devel \
        graphviz \
        graphviz-devel \
        wget \
        postgresql12-server \
        postgresql12 \
        qtbase5-dev \
        qt5-qtbase-devel \
        qt5-qmake \
        coreutils
else
    apt-get install -y \
        pgloader \
        libgeos-dev \
        libgdal-dev \
        libproj-dev \
        graphviz \
        graphviz-dev \
        postgresql \
        libopencv-dev \
        libopencv-core-dev \
        cmake \
        ninja-build \
        qt5-qmake \
        qtbase5-dev \
        qtchooser \
        qtbase5-dev-tools \
        qttools5-dev-tools \
        qtchooser \
        coreutils
        libopencv-dev libopencv-core-dev \
        build-essential cmake ninja-build \
        qtbase5-dev qt5-qmake qtchooser \
        libgeos-dev libgdal-dev libproj-dev graphviz \
        libgl1-mesa-glx libxext6 libxrender-dev

export OpenCV_DIR=/usr/lib/x86_64-linux-gnu/cmake/opencv4
fi


pip install --global-option=build_ext --global-option="-I/usr/include/graphviz/" --global-option="-L/usr/lib/graphviz/" pygraphviz
pip uninstall -y pyqt5
pip install --upgrade pyqt5
