ARG         FROM=docker.io/rockylinux/rockylinux:9.8
FROM        ${FROM}

ENV         WORKSPACE="/opt/build"
ENV         OUTPUT_DIR="/output"
WORKDIR     ${WORKSPACE}

COPY        files ${WORKSPACE}/files
COPY        scripts ${WORKSPACE}/scripts

VOLUME      ["${OUTPUT_DIR}"]

ENTRYPOINT  ["/opt/build/scripts/build.sh"]
