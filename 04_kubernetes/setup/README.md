# Getting a container runtime for `kind`

`04_kubernetes` is the **only** part of this repository that needs anything beyond
`pip install -r requirements.txt` — because GKE is *managed Kubernetes*, Kubernetes is open source,
and `kind` can therefore run a **real** cluster on your machine. Every other part is logic and
arithmetic.

`kind` runs each Kubernetes node as a **container**, so it needs a container runtime.

---

## Pick one

| | when | cost |
|---|---|---|
| **A. Use a desktop container tool you already have** | Docker Desktop or Rancher Desktop is installed and its engine starts | nothing to install. Start the engine and go |
| **B. Install Docker Engine inside WSL** | the desktop tool won't cooperate, or you'd rather not depend on it | ~2 minutes, needs `sudo`, and a `wsl --shutdown` |
| **C. Skip it** | you want the other ten parts | nothing. `00_setup/check_env.py` will keep reporting this part as blocked, which is accurate |

**Try A first.** If a desktop tool is installed, its engine being stopped is usually one click in
its own window, and option B then has to coexist with it — see the conflict below.

## A. The desktop tool

Open its window and confirm the container engine is **running**, not just the app. A stopped backend
looks exactly like a broken install from the terminal:

```
$ docker info
failed to connect to the docker API at unix:///var/run/docker.sock;
check if the path is correct and if the daemon is running
```

That message means the **CLI is on PATH and the daemon is not up** — not that Docker is missing.

If the tool offers **WSL integration**, enable it for the distro you work in. `kind` will then use
its engine with nothing else to install.

## B. Docker Engine inside WSL

```bash
bash 04_kubernetes/setup/install_docker_wsl.sh   # as your normal user, NOT with sudo
# then, from Windows:
wsl --shutdown
# then in a new WSL shell:
bash 04_kubernetes/setup/install_kind.sh          # no sudo needed
```

**Run the first script as yourself, not under `sudo`.** It calls `sudo` where it needs to. Run whole
under `sudo` and it adds **root** to the docker group instead of you.

What it does: checks you are on Ubuntu/Debian inside WSL, checks TLS to `download.docker.com`
actually verifies, enables **systemd** in `/etc/wsl.conf` if it is off, adds Docker's official apt
repository and signing key, installs `docker-ce`, and adds you to the `docker` group. It is
idempotent.

### Two things it refuses to do

**It never works around a TLS error.** No `curl -k`, no `--trusted-host`, no
`NODE_TLS_REJECT_UNAUTHORIZED=0`. If you are behind a TLS-inspecting proxy and the download fails,
the fix is to install that proxy's root CA into the distro's trust store:

```bash
sudo cp your-root-ca.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

An unverified download of a **package signing key** is the one download you should never do
unverified — the whole point of the key is that everything after it is trusted.

**It does not touch your desktop container tool.** See the conflict, next.

### The conflict, *if* you enable a desktop tool's WSL integration

A desktop container tool can mount its own daemon socket into a WSL distro — that is what its **WSL
integration** setting does. If it is **on** for the distro where you also run Docker Engine, both
want `/var/run/docker.sock` and the symptom is a `docker` that works one day and not the next
depending on start order.

**This is conditional, and by default it does not apply.** Checked on the machine this was written
for:

```
rdctl list-settings   ->   "WSL": { "integrations": {} }
ls -l /var/run/docker.sock  ->  srw-rw---- root docker
```

Integration was **off** and the socket belongs to Docker Engine's systemd unit. No contention.

**Leave the integration off and there is nothing to resolve.** If you deliberately turn it on for a
distro, pick one owner of the socket there — don't run both.

> ⚠️ **An earlier version of this file said turning WSL integration off was the fix for the PATH
> problem below.** That was wrong: integration was already off and the directories were on PATH
> anyway. See the next section for what actually causes it.

### `systemd` and the restart

WSL distros do not run `systemd` unless `/etc/wsl.conf` asks for it, and Docker is a systemd
service. The script writes:

```ini
[boot]
systemd=true
```

**That only takes effect after `wsl --shutdown` from Windows** — not `exit`, not closing the
terminal. After the restart Docker starts on boot and your `docker` group membership is live.

## The credential-helper trap — measured, not predicted

This one actually happened on the machine these scripts were written for, **after** Docker Engine
was installed and working:

```
$ docker run --rm hello-world
docker-credential-secretservice: error while loading shared libraries:
libsecret-1.so.0: cannot open shared object file: No such file or directory
docker: error getting credentials - err: exit status 127
```

Docker was fine. `systemd` was running, `/usr/bin/docker` won on PATH, the daemon was up in 3
seconds, cgroup v2. The failure was **a Linux credential helper injected from a Windows mount**:

```
$ which -a docker-credential-secretservice
/mnt/c/Program Files/Rancher Desktop/.../linux/bin/docker-credential-secretservice
```

**When no credential store is configured, the Docker CLI picks one by looking on PATH.** It found
that helper and could not run it — a headless WSL distro has neither `libsecret` nor a D-Bus secret
service.

**Two fixes that do not work, and why:**

| | |
|---|---|
| `"credsStore": ""` in `~/.docker/config.json` | the CLI treats **empty as "auto-detect"** and finds the helper again. Verified — it changed nothing |
| `apt install libsecret-1-0` | the helper would load, then fail anyway: it needs a **running secret service** to talk to, which WSL has no reason to have |

### Where those directories actually come from

**Not from WSL integration.** WSL copies the **entire Windows PATH** into every distro — the
`appendWindowsPath` interop setting, on by default. A desktop container tool puts its bin
directories on the Windows PATH so its CLI works in PowerShell, and WSL hands them to Linux as a
side effect. Some of those directories contain **Linux** binaries:

```
C:\Program Files\Rancher Desktop\resources\resources\win32\bin\
C:\Program Files\Rancher Desktop\resources\resources\win32\docker-cli-plugins\
C:\Program Files\Rancher Desktop\resources\resources\linux\bin\          <- Linux binaries
C:\Program Files\Rancher Desktop\resources\resources\linux\docker-cli-plugins\
```

All four on the **Windows** PATH, therefore all four on the Linux PATH, **with integration off**.

**The fix is to take those directories off PATH.** `install_docker_wsl.sh` detects them and appends
a marked, reversible strip to **both `~/.bashrc` and `~/.profile`** — delete the block to undo.

> **Both files, and that is not belt-and-braces.** Ubuntu's `~/.bashrc` opens with an early
> `return` for non-interactive shells:
>
> ```
> case $- in
>     *i*) ;;
>       *) return;;
> esac
> ```
>
> A block appended to the **end** of it never runs for `bash -lc`, for scripts, or for anything
> automated — only when you type in a terminal. An earlier version of this script wrote only to
> `~/.bashrc`, which **looked** fixed and left every non-interactive `docker pull` broken:
>
> ```
> interactive shell   -> works
> bash -lc            -> Rancher dirs on PATH: 4, PULL FAILED
> ```
>
> `~/.bashrc` covers interactive non-login shells; `~/.profile` covers login shells, which is what
> `bash -lc` runs. You need both.
>
> Neither covers a bare `wsl --exec bash script.sh`, which reads no shell config at all. If you
> automate against this distro, either use a login shell or set `appendWindowsPath=false`.

The heavier alternative is `appendWindowsPath=false` in `/etc/wsl.conf`, which removes **every**
Windows directory from the Linux PATH. That fixes this and costs you every other Windows tool you
reach from WSL, so the targeted strip is usually the better trade.

> This is why the script checks PATH at all. The error message names a **missing shared library**,
> and the cause is **the Windows PATH being inherited** — two facts with nothing visible connecting
> them, and a plausible-sounding wrong answer ("turn off WSL integration") sitting right next to the
> real one.

## The PATH trap, which is specific to WSL

Windows directories are on your PATH inside WSL, so a Windows container tool's `docker` and
`kubectl` appear to be installed:

```
$ which -a docker
/mnt/c/Program Files/.../resources/linux/bin/docker
```

Two consequences:

- **After installing Docker Engine**, `/usr/bin` comes earlier in PATH than `/mnt/c/...` on a
  standard Ubuntu, so the Linux binary wins. Verify rather than assume:
  `command -v docker` should print `/usr/bin/docker`.
- **`kubectl` on PATH may not be kubectl.** Rancher Desktop ships **`kuberlr`**, a version-switching
  wrapper that downloads and delegates to the real kubectl matching your cluster. Sensible — it
  avoids client/server skew — but it **rejects flags real kubectl accepts** (`kubectl version
  --client` errors with *unknown flag*), so a script shelling out to it fails for reasons unrelated
  to your cluster. `install_kind.sh` installs a native Linux `kubectl` into `~/.local/bin` for this
  reason, and warns you if a Windows binary still shadows it.

## Verified end to end on a real machine

Ubuntu 24.04.5 in WSL2, after running both scripts:

```
docker   29.8.1        /usr/bin/docker      daemon up ~3s, cgroup v2, overlayfs
kind     v0.33.0       ~/.local/bin/kind    checksum verified
kubectl  v1.37.1       ~/.local/bin/kubectl checksum verified

$ kind create cluster --name ace
 ✓ Ensuring node image (kindest/node:v1.37.0)
 ✓ Starting control-plane / Installing CNI / Installing StorageClass

$ kubectl get nodes
ace-control-plane   Ready   control-plane   v1.37.0   containerd://2.3.4

$ kubectl create deployment web --image=nginx --replicas=2
deployment "web" successfully rolled out     2/2 Running
```

**A real Kubernetes 1.37.0 control plane, running as a container**, with a workload scheduled on it.
That is the whole reason `04_kubernetes` exists: GKE is *managed Kubernetes*, and Kubernetes is the
one piece of ACE that genuinely runs on your laptop.

## What was checked before these were staged

Run on this machine, against the live endpoints, without installing anything:

```
bash syntax                both scripts parse
version resolution         kind v0.33.0, kubectl v1.37.1 resolved at run time
asset URLs                 all 5 return HTTP 200, including kind's .sha256sum
checksum form              verifies a real kubectl download
tampered file              correctly REJECTED
```

That last line is the one worth proving rather than assuming. A checksum step that silently passes
everything is worse than none, because it buys confidence it has not earned.

## Verify

```bash
command -v docker kind kubectl     # all should be Linux paths
docker run --rm hello-world
kind create cluster --name ace
kubectl get nodes
kind delete cluster --name ace
```

`kind create cluster` pulls a node image on first run, so the first one is slow and every one after
is not.

## Uninstalling

```bash
rm -f ~/.local/bin/kind ~/.local/bin/kubectl        # option B, the no-sudo half
sudo apt-get remove --purge docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo rm -f /etc/apt/sources.list.d/docker.list /etc/apt/keyrings/docker.gpg
```

Leaving `systemd=true` in `/etc/wsl.conf` is harmless and generally an improvement.
