#!/bin/bash

VER=${1:-9.8}
SRC_VER=${2:-0.1.0}

podman build -t docker.io/skbcloudx/bcocinero-builder \
  --build-arg=FROM=docker.io/skbcloudx/rockylinux:${VER} .
podman run -it --privileged -v $(pwd)/output:/output \
  --rm docker.io/skbcloudx/bcocinero-builder ${VER} ${SRC_VER}

