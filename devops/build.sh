#!/usr/bin/env bash

set -ex

# See https://stackoverflow.com/a/246128/176882
export ROOT_LOC="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

export DOCKER_BUILDKIT=1

export DOCKER_CLI_EXPERIMENTAL=enabled

# Change to the script's root directory location
cd ${ROOT_LOC}

# Detect the current branch for VCS_REF
export VCS_REF=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
echo "Building with VCS_REF=${VCS_REF}"

# Build the images in dependence order
while [ $# -ge 1 ]; do
    if [ "$1" == "wbia-base" ]; then
        docker build \
            --compress \
            --progress=plain \
            -t wildme/wbia-base:latest \
            base
    elif [ "$1" == "wbia-provision" ]; then
        docker build \
            --compress \
            --progress=plain \
            --no-cache \
            --build-arg VCS_REF=${VCS_REF} \
            -t wildme/wbia-provision:latest \
            provision
    elif [ "$1" == "wbia" ] || [ "$1" == "wildbook-ia" ]; then
        docker build \
            --compress \
            --progress=plain \
            --build-arg VCS_REF=${VCS_REF} \
            -t wildme/wbia:latest \
            -t wildme/wildbook-ia:latest \
            --no-cache \
            .
    elif [ "$1" == "wbia-develop" ]; then
        cd ../
        docker build \
            --compress \
            -t wildme/wbia:develop \
            devops/develop
        cd devops/
    else
        echo "Image $1 not found"
        exit 1
    fi
    shift
done
