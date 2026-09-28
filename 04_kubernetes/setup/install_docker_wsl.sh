#!/usr/bin/env bash
# Install Docker Engine inside a WSL2 Ubuntu/Debian distro, for `kind`.
#
# RUN THIS AS YOUR NORMAL USER, NOT WITH sudo:
#
#     bash 04_kubernetes/setup/install_docker_wsl.sh
#
# The script calls sudo itself where it needs to. Running the whole thing as
# root would add ROOT to the docker group instead of you, which is not what
# you want and is annoying to undo.
#
# It is idempotent: run it twice and the second run changes nothing.
#
# WHAT IT DOES
#   1. checks you are on a supported distro inside WSL
#   2. checks TLS to download.docker.com actually works
#   3. enables systemd in /etc/wsl.conf if it is not already on
#   4. adds Docker's official apt repository and signing key
#   5. installs docker-ce and the compose/buildx plugins
#   6. adds you to the docker group
#
# WHAT IT DELIBERATELY DOES NOT DO
#   - it never passes -k / --insecure to curl, and never sets
#     NODE_TLS_REJECT_UNAUTHORIZED=0 or pip --trusted-host. If TLS fails
#     behind an inspecting proxy, the fix is to install the proxy's root CA
#     into the distro's trust store. Working around a certificate error
#     hides exactly the failure you want to see.
#   - it does not touch Docker Desktop or Rancher Desktop. Read
#     setup/README.md first if either is installed - there is a real
#     conflict over /var/run/docker.sock.

set -euo pipefail

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die()  { printf '\n\033[31mERROR: %s\033[0m\n\n' "$*" >&2; exit 1; }

# --------------------------------------------------------------- 1. preflight
say "Checking this is somewhere Docker Engine belongs"

[ "$(id -u)" -ne 0 ] || die "Run this as your normal user, not with sudo.
    The script uses sudo itself. As root it would add root to the docker
    group and leave you no better off."

grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null \
  || die "This does not look like WSL. On a normal Linux host, follow
    Docker's own instructions instead - this script makes WSL-specific
    changes to /etc/wsl.conf."

[ -r /etc/os-release ] || die "No /etc/os-release; cannot identify the distro."
# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-}" in
  ubuntu|debian) : ;;
  *) die "Distro '${ID:-unknown}' is not supported by this script.
    It targets Ubuntu and Debian, which is what Docker's apt repo serves." ;;
esac
info "distro     ${PRETTY_NAME:-$ID} (${VERSION_CODENAME:-unknown})"
info "arch       $(dpkg --print-architecture)"

if command -v dockerd >/dev/null 2>&1; then
  info "dockerd    already installed - this run will just re-check the setup"
fi

# ------------------------------------------------------------------ 2. TLS
say "Checking TLS to download.docker.com"
if curl -fsS -o /dev/null --max-time 30 https://download.docker.com/linux/ubuntu/gpg; then
  info "ok - the certificate chain verifies"
else
  die "Cannot fetch Docker's signing key over HTTPS.

    If you are behind a TLS-inspecting proxy, its root CA is not in this
    distro's trust store. Install it properly:

        sudo cp your-root-ca.crt /usr/local/share/ca-certificates/
        sudo update-ca-certificates

    Do NOT re-run this with curl -k. An unverified download of a package
    signing key is the one download you should never do unverified."
fi

say "Priming sudo (you will be asked for your password once)"
sudo -v

# -------------------------------------------------------------- 3. systemd
say "Checking systemd"
if [ -d /run/systemd/system ]; then
  info "systemd is running - docker will start as a normal service"
  SYSTEMD_WAS_OFF=0
else
  info "systemd is NOT running in this distro"
  if grep -qE '^\s*systemd\s*=\s*true' /etc/wsl.conf 2>/dev/null; then
    info "but /etc/wsl.conf already enables it - you just need a restart"
  else
    info "enabling it in /etc/wsl.conf"
    if [ -f /etc/wsl.conf ] && ! grep -q '^\[boot\]' /etc/wsl.conf; then
      printf '\n[boot]\nsystemd=true\n' | sudo tee -a /etc/wsl.conf >/dev/null
    elif [ -f /etc/wsl.conf ]; then
      sudo sed -i '/^\[boot\]/a systemd=true' /etc/wsl.conf
    else
      printf '[boot]\nsystemd=true\n' | sudo tee /etc/wsl.conf >/dev/null
    fi
    info "written:"
    sed 's/^/      /' /etc/wsl.conf
  fi
  SYSTEMD_WAS_OFF=1
fi

# ----------------------------------------------------------------- 4. repo
say "Adding Docker's apt repository"
sudo install -m 0755 -d /etc/apt/keyrings
if [ ! -s /etc/apt/keyrings/docker.gpg ]; then
  curl -fsSL --max-time 60 "https://download.docker.com/linux/${ID}/gpg" \
    | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  info "signing key -> /etc/apt/keyrings/docker.gpg"
else
  info "signing key already present"
fi
sudo chmod a+r /etc/apt/keyrings/docker.gpg

CODENAME="${VERSION_CODENAME:-$(lsb_release -cs 2>/dev/null || true)}"
[ -n "$CODENAME" ] || die "Could not determine the distro codename."
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/${ID} ${CODENAME} stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
info "repo        ${ID} ${CODENAME} stable"

# -------------------------------------------------------------- 5. install
say "Installing Docker Engine (this is the slow part)"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
info "installed   $(/usr/bin/docker --version 2>/dev/null || echo 'docker (version pending start)')"

# ---------------------------------------------------------------- 6. group
say "Adding you to the docker group"
sudo groupadd -f docker
if id -nG "$USER" | tr ' ' '\n' | grep -qx docker; then
  info "$USER is already in the docker group"
else
  sudo usermod -aG docker "$USER"
  info "$USER added - this takes effect on your NEXT shell, not this one"
fi

# ------------------------------------------- 7. Windows tools on PATH
say "Checking for a Windows container tool on PATH"
#
# WSL copies the WINDOWS PATH into every distro - that is the `interop`
# setting `appendWindowsPath`, on by default. So a Windows container tool
# that puts its bin directories on the Windows PATH (they all do, so its
# CLI works in PowerShell) has them on your Linux PATH too. Some of those
# directories contain LINUX binaries, including docker credential helpers.
#
# NOTE THIS HAS NOTHING TO DO WITH "WSL INTEGRATION". Verified on the
# machine this was written for: Rancher Desktop's WSL integration was OFF
# for the distro, and its four directories were on the Linux PATH anyway.
# Turning integration off does not fix this, because integration was never
# what caused it.
#
# That breaks `docker pull` in a way that looks nothing like a PATH problem:
#
#   docker-credential-secretservice: error while loading shared libraries:
#   libsecret-1.so.0: cannot open shared object file
#   docker: error getting credentials - err: exit status 127
#
# The Docker CLI picks a credential helper by LOOKING ON PATH when none is
# configured, finds that one, and it cannot run - a headless WSL distro has
# neither libsecret nor a D-Bus secret service. Setting credsStore to ""
# does NOT help: the CLI treats empty as "auto-detect" and finds it again.
# Installing libsecret does not help either, because the helper still needs
# a secret service to talk to.
#
# The fix is to take those directories off PATH.
WIN_TOOL_DIRS="$(echo "$PATH" | tr ':' '\n' \
  | grep -iE 'Rancher Desktop|Docker/Docker/resources' || true)"

if [ -z "$WIN_TOOL_DIRS" ]; then
  info "none found - nothing to do"
else
  info "these Windows tool directories are on your PATH:"
  echo "$WIN_TOOL_DIRS" | sed 's/^/      /'
  MARKER="# gcloud-learning-ace: drop Windows container tools from PATH"
  # BOTH FILES, and that is not belt-and-braces. Ubuntu's ~/.bashrc opens
  # with an early `return` for non-interactive shells, so a block appended
  # to the END of it never runs for `bash -lc`, for scripts, or for
  # anything automated - only when you type in a terminal. An earlier
  # version wrote only to ~/.bashrc, which looked fixed and left every
  # non-interactive `docker pull` broken.
  #   ~/.bashrc  -> interactive non-login shells
  #   ~/.profile -> login shells, which is what `bash -lc` runs
  for rc in "${HOME}/.bashrc" "${HOME}/.profile"; do
    if grep -qF "$MARKER" "$rc" 2>/dev/null; then
      info "$(basename "$rc") already strips them"
      continue
    fi
    cat >> "$rc" <<'RCBLOCK'

# gcloud-learning-ace: drop Windows container tools from PATH
# WSL copies the whole Windows PATH into this distro, and some of those
# directories hold LINUX binaries - including a docker credential helper
# that cannot run here, which breaks `docker pull`. Remove this block to undo.
PATH="$(printf '%s' "$PATH" | tr ':' '\n' \
  | grep -vi 'Rancher Desktop' \
  | grep -vi 'Docker/Docker/resources' \
  | paste -sd: -)"
export PATH
RCBLOCK
    info "added a strip to $(basename "$rc") (remove the block to undo)"
  done
  info ""
  info "The heavier alternative is appendWindowsPath=false in /etc/wsl.conf,"
  info "which removes EVERY Windows directory from the Linux PATH. That fixes"
  info "this and costs you every other Windows tool you reach from WSL, so"
  info "the targeted strip above is usually the better trade."
fi

# ------------------------------------------------------------------ finish
say "Done. What happens next depends on systemd"
if [ "$SYSTEMD_WAS_OFF" -eq 1 ]; then
  cat <<'EOF'
    systemd was off, so Docker cannot start until this distro restarts.

    FROM WINDOWS (PowerShell or CMD), run:

        wsl --shutdown

    Then open a new WSL shell. Docker will start automatically, and your
    docker group membership will be live in that shell too.
EOF
else
  sudo systemctl enable --now docker >/dev/null 2>&1 || true
  cat <<'EOF'
    Docker has been enabled and started.

    Your docker group membership is not active in THIS shell. Either open
    a new WSL shell, or run:  newgrp docker
EOF
fi

cat <<'EOF'

    THEN VERIFY, in a NEW shell:

        command -v docker          # expect /usr/bin/docker
        docker run --rm hello-world

    If `command -v docker` still points at /mnt/c/..., a Windows container
    tool is shadowing it on PATH. See setup/README.md.

    Once docker works:

        bash 04_kubernetes/setup/install_kind.sh
EOF
