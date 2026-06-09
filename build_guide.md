# Building WBIA Docker Images

## Overview

Four-stage multi-stage Docker build. Each stage depends on the previous.

```
wbia-base  →  wbia-provision  →  wbia (final)  →  wbia-develop
(8.97 GB)     (22.8 GB)         (18.8 GB)        (19.8 GB)
```

| Stage | Dockerfile | Image | Purpose |
|-------|-----------|-------|---------|
| base | `devops/base/Dockerfile` | `wildme/wbia-base:latest` | CUDA 11.7, Ubuntu 22.04, Python 3.10, system deps |
| provision | `devops/provision/Dockerfile` | `wildme/wbia-provision:latest` | Clone repos, install PyTorch + all Python deps |
| final | `devops/Dockerfile` | `wildme/wbia:latest` | Pull latest git, smoke tests, runtime entrypoint |
| develop | `devops/develop/Dockerfile` | `wildme/wbia:develop` | Overlay local source on final image |

## Prerequisites

- Docker with BuildKit (`DOCKER_BUILDKIT=1`)
- ~50 GB free disk space
- GPU optional (builds without CUDA hardware fine)

## Build

```bash
# One-shot all stages
cd devops
./build.sh wbia-base wbia-provision wbia wbia-develop

# Or individually:
./build.sh wbia-base
./build.sh wbia-provision
./build.sh wbia
./build.sh wbia-develop
```

## Known Issues

### Submodule .git + setuptools-scm

If this repo is a submodule (`.git` is a gitfile pointing to a parent repo), `setuptools-scm` can't detect the version inside Docker. The develop Dockerfile sets `SETUPTOOLS_SCM_PRETEND_VERSION` as a workaround.

### Editable install (PEP 660)

`pip install -e .` fails because scikit-build doesn't support `build_editable`. Use `pip install .` (non-editable) instead. The develop stage already handles this.

## Run

```bash
docker run --gpus all -p 5000:5000 wildme/wbia:latest

# With local source:
docker run --gpus all -p 5000:5000 wildme/wbia:develop
```

Command to rebuild after code change:
```bash
DOCKER_BUILDKIT=1 DOCKER_CLI_EXPERIMENTAL=enabled docker build --compress -t wildme/wbia:develop -f devops/develop/Dockerfile .
```
