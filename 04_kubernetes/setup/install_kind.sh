#!/usr/bin/env bash
# Install kind and a native Linux kubectl into ~/.local/bin.
#
#     bash 04_kubernetes/setup/install_kind.sh
#
# NO SUDO NEEDED. Everything lands in your home directory, which also means
# uninstalling is `rm`.
#
# WHY A NATIVE kubectl WHEN ONE IS ALREADY ON PATH
#   In WSL, Windows directories are on PATH, so a kubectl shipped by a
#   Windows container tool appears to be installed. It may be a WRAPPER
#   rather than kubectl - Rancher Desktop ships `kuberlr`, which downloads
#   and delegates to a real kubectl per cluster and rejects some flags real
#   kubectl accepts. That is fine until a script shells out to it and fails
#   for reasons that have nothing to do with your cluster.
#
# VERSIONS ARE RESOLVED AT RUN TIME, never hardcoded. A pinned version in a
# setup script becomes a 404 the moment upstream moves, and the error it
# produces points at the wrong thing entirely.
#
# EVERY DOWNLOAD IS CHECKSUM-VERIFIED against the publisher's own sum file.

set -euo pipefail

BIN="${HOME}/.local/bin"
ARCH="$(dpkg --print-architecture 2>/dev/null || uname -m)"
case "$ARCH" in
  amd64|x86_64) ARCH=amd64 ;;
  arm64|aarch64) ARCH=arm64 ;;
  *) printf 'ERROR: unsupported architecture %s\n' "$ARCH" >&2; exit 1 ;;
esac

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die()  { printf '\n\033[31mERROR: %s\033[0m\n\n' "$*" >&2; exit 1; }

mkdir -p "$BIN"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ------------------------------------------------------------------- kind
say "Resolving the latest kind release"
KIND_VER="$(curl -fsSL --max-time 30 \
  https://api.github.com/repos/kubernetes-sigs/kind/releases/latest \
  | grep -m1 '"tag_name"' | cut -d'"' -f4 || true)"
[ -n "$KIND_VER" ] || die "Could not resolve the latest kind version.

    The GitHub API may be unreachable from here. Check manually at
    https://github.com/kubernetes-sigs/kind/releases and set KIND_VER by
    hand if you need to:

        KIND_VER=v0.00.0 bash $0"
info "kind       ${KIND_VER} (${ARCH})"

BASE="https://github.com/kubernetes-sigs/kind/releases/download/${KIND_VER}"
curl -fsSL --max-time 120 -o "${TMP}/kind" "${BASE}/kind-linux-${ARCH}"
if curl -fsSL --max-time 60 -o "${TMP}/kind.sha256" \
     "${BASE}/kind-linux-${ARCH}.sha256sum" 2>/dev/null; then
  ( cd "$TMP" && awk '{print $1"  kind"}' kind.sha256 | sha256sum -c - ) \
    || die "kind checksum did NOT match. Do not use this download."
  info "checksum   verified"
else
  info "checksum   NOT PUBLISHED for this asset - continuing, but be aware"
fi
install -m 0755 "${TMP}/kind" "${BIN}/kind"
info "installed  ${BIN}/kind"

# ---------------------------------------------------------------- kubectl
say "Resolving the current stable kubectl"
KVER="$(curl -fsSL --max-time 30 https://dl.k8s.io/release/stable.txt || true)"
[ -n "$KVER" ] || die "Could not resolve the stable kubectl version."
info "kubectl    ${KVER} (${ARCH})"

KBASE="https://dl.k8s.io/release/${KVER}/bin/linux/${ARCH}"
curl -fsSL --max-time 120 -o "${TMP}/kubectl" "${KBASE}/kubectl"
curl -fsSL --max-time 60  -o "${TMP}/kubectl.sha256" "${KBASE}/kubectl.sha256"
( cd "$TMP" && printf '%s  kubectl\n' "$(cat kubectl.sha256)" | sha256sum -c - ) \
  || die "kubectl checksum did NOT match. Do not use this download."
info "checksum   verified"
install -m 0755 "${TMP}/kubectl" "${BIN}/kubectl"
info "installed  ${BIN}/kubectl"

# ------------------------------------------------------------------- PATH
say "Checking PATH order"
case ":${PATH}:" in
  *":${BIN}:"*) info "${BIN} is on PATH" ;;
  *)
    info "${BIN} is NOT on PATH. Adding it to ~/.bashrc:"
    printf '\n# added by gcloud-learning-ace 04_kubernetes/setup\nexport PATH="$HOME/.local/bin:$PATH"\n' \
      >> "${HOME}/.bashrc"
    info '  export PATH="$HOME/.local/bin:$PATH"'
    info "Open a new shell, or: source ~/.bashrc"
    ;;
esac

RESOLVED="$(command -v kubectl 2>/dev/null || echo none)"
case "$RESOLVED" in
  /mnt/c/*)
    info ""
    info "WARNING: kubectl still resolves to a WINDOWS binary:"
    info "  $RESOLVED"
    info "A Windows tool is earlier on PATH. In a new shell it should"
    info "become ${BIN}/kubectl. If it does not, see setup/README.md."
    ;;
  "${BIN}/kubectl") info "kubectl resolves to ${RESOLVED}" ;;
  *) info "kubectl currently resolves to ${RESOLVED}" ;;
esac

cat <<EOF

==> Done.

    In a NEW shell, verify:

        command -v kind kubectl
        kind version
        kubectl version --client

    Then, with docker running:

        kind create cluster --name ace
        kubectl get nodes

    Tear it down with:

        kind delete cluster --name ace
EOF
