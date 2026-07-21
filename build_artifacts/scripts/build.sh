#!/bin/bash

set -exo pipefail

VER=${1:-9.8}
SRC_VER=${2:-0.1.0}

# Check where ${VER} is in RL download site
WHERE=
DLURL="https://dl.rockylinux.org"
PUBURL="${DLURL}/pub/rocky/${VER}/isos/"
VAULTURL="${DLURL}/vault/rocky/${VER}/isos/"
scode=$(curl -sIo /dev/null -w '%{http_code}' "${PUBURL}")
if [[ "${scode}" -eq 200 ]]; then
  WHERE="pub"
else
  scode=$(curl -sIo /dev/null -w '%{http_code}' "${VAULTURL}")
  if [[ "${scode}" -eq 200 ]]; then
    WHERE="vault"
  fi
fi
if [[ -z ${WHERE} ]]; then
  echo "Abort) I cannot find ${VER} in RL download site."
  exit 1
fi

# Reset yum repo to the RL official site
mv -f /etc/yum.repos.d /etc/yum.repos.d.bak
mkdir /etc/yum.repos.d
cp ${WORKSPACE}/files/yum.repos.d/* /etc/yum.repos.d/
sed -i "s/VERSION/${VER}/g;s/WHERE/${WHERE}/g" /etc/yum.repos.d/*.repo

# install packages
PKGS=(git python3-pip)
dnf -y install ${PKGS[@]}

# get bcocinero source 
git clone -b ${SRC_VER} https://github.com/skbcloudx/bcocinero.git

# install uv
python3 -m pip install uv

# build bcocinero
uv build --directory ${WORKSPACE}/bcocinero --out-dir ${OUTPUT_DIR}

# get requirements
if [[ -f ${WORKSPACE}/bcocinero/requirements.txt ]]; then
    mkdir -p ${WORKSPACE}/requirements
    python3 -m pip download --dest ${WORKSPACE}/requirements \
        --requirement ${WORKSPACE}/bcocinero/requirements.txt
else
    echo "Abort: cannot find ${WORKSPACE}/bcocinero/requirements.txt."
    exit 1
fi

# archive requirements wheel house
pushd ${WORKSPACE}/requirements
    tar czf ${OUTPUT_DIR}/requirements.tar.gz *
popd
