#!/usr/bin/env bash
# Installe gVisor (runsc) à une version épinglée et l'enregistre comme runtime Docker « runsc ».
# Usage : sudo scripts/install-gvisor.sh [release]   (release par défaut : GVISOR_RELEASE)
set -euo pipefail

release="${1:-${GVISOR_RELEASE:?GVISOR_RELEASE or an argument is required}}"
arch=$(uname -m)
url="https://storage.googleapis.com/gvisor/releases/release/${release}/${arch}"
workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT

cd "$workdir"
curl -fsSLO "${url}/gvisor.tar.bz2"
curl -fsSLO "${url}/gvisor.tar.bz2.sha512"
sha512sum --check gvisor.tar.bz2.sha512
tar -xjf gvisor.tar.bz2

install -m 0755 runsc containerd-shim-runsc-v1 /usr/local/bin/
install -d /usr/local/bin/gvisor-bin
install -m 0755 gvisor-bin/* /usr/local/bin/gvisor-bin/

/usr/local/bin/runsc install
systemctl restart docker
runsc --version
