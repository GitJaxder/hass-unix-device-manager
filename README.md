# Unix Device Manager for Home Assistant

Monitor and update Linux/unix hosts from Home Assistant over SSH. Nothing needs to be installed on the remote device.

## Features

- **Sensors**
  - **OS version**, read from `/etc/os-release`.
  - **Updates available**: the count of pending updates, with the package names in a `packages` attribute (capped at 50).
  - **IP address** (diagnostic).
  - **Hardware**: CPU usage, CPU temperature, memory usage, disk usage and free space (root filesystem), and last boot time. Memory used, swap usage and 1/5/15-minute load averages are available but disabled by default. These poll every 60 seconds, separately from the update check, and keep reporting while an upgrade runs. A sensor the host can't report (for example temperature on a VM with no thermal zone) is not created.
- **Device info**: manufacturer, model, OS version (shown as the device's software version), architecture (hardware version) and MAC address. Hardware details come from firmware data on x86 and VMs, or the device tree on Raspberry Pi and other ARM boards.
- **OS updates** (update entity): shows as available in **Settings → Updates** when packages are pending, lists them in the release notes, and installs them with a progress spinner while the upgrade runs.
- **Buttons**: **Update repositories** and **Update OS**. Sensors refresh after either one runs. While one is running, pressing either button again (or installing from the update entity) is refused with a message instead of queueing another run, and an OS upgrade started from the button also shows as in progress on the update entity.
- **Package managers**: apt, dnf, yum, apk, pacman (via `checkupdates` from `pacman-contrib`) and zypper, auto-detected.
- **Options**: update check interval (default 60 minutes, 5 to 1440) and hardware sensor interval (default 60 seconds, 10 to 3600).

## Installation

### HACS (custom repository)

1. In HACS, open the menu (⋮) and choose **Custom repositories**.
2. Add `https://github.com/GitJaxder/hass-unix-device-manager` with category **Integration**.
3. Download **Unix Device Manager** and restart Home Assistant.

### Manual

Copy `custom_components/unix_manager` into your Home Assistant `custom_components` directory and restart.

Then go to **Settings → Devices & services → Add integration → Unix Device Manager**.

Requires a current Home Assistant release (the code uses Python 3.12+ syntax). Brand images ship in `brand/`, which Home Assistant 2026.3 and newer will display.

## Preparing a remote device

Use a dedicated user with key authentication.

**1. Create the user** (Debian/Ubuntu example; use your distro's equivalent):

```bash
adduser --disabled-password --gecos "" hass-mgr
```

**2. Generate a key on the Home Assistant host** (no passphrase; passphrase-protected keys are not supported yet):

```bash
mkdir -p /config/ssh && chmod 700 /config/ssh
ssh-keygen -t ed25519 -f /config/ssh/hass_mgr -N "" -C "ha-unix-manager"
chmod 600 /config/ssh/hass_mgr
cat /config/ssh/hass_mgr.pub
```

**3. Install the public key on the remote device** as `hass-mgr`:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
# append the single-line public key to ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

**4. Give the user passwordless sudo** (only needed for the two buttons; listing updates does not need root):

```bash
echo 'hass-mgr ALL=(root) NOPASSWD: ALL' > /etc/sudoers.d/hass-mgr
chmod 440 /etc/sudoers.d/hass-mgr
visudo -c
```

**5. Test from the Home Assistant host:**

```bash
ssh -i /config/ssh/hass_mgr hass-mgr@<host> 'sudo -n true && echo ok'
```

In the integration's setup form, enter the host, port, username, and the key file path (for example `/config/ssh/hass_mgr`). A password can be used instead, or as well.

The next step shows the host's SSH key fingerprint. Compare it with the output of `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on the device (the form names the right file for the key type) before submitting. No credentials are sent until you confirm.

### Optional: restrict the key

Prefix the key's line in `authorized_keys` so it only works from your Home Assistant machine:

```
from="192.168.1.0/24",no-port-forwarding,no-agent-forwarding,no-X11-forwarding ssh-ed25519 AAAA... ha-unix-manager
```

Use an IP or CIDR range, not a hostname. If logins start failing, check `journalctl -u ssh` on the remote device: a mismatch logs "Authentication tried for ... with correct key but not from a permitted host" along with the address sshd saw.

## Notes and limitations

- **Update OS** (the button or the update entity) runs the normal package upgrade (for example `apt-get upgrade`), not a distribution release upgrade. The button waits for it to finish, up to an hour, and reports failures in the UI.
- Refresh and upgrade commands run under `nohup`, so a dropped SSH connection cannot kill a package manager mid-transaction. Only one operation runs per host at a time.
- **Host keys are pinned.** The key confirmed at setup is the only one accepted. If it changes (for example after reinstalling the OS), the integration stops connecting and Home Assistant asks you to re-authenticate, showing the new fingerprint to accept. Entries created before v0.3.0 pin the key they see on their first connection after the upgrade and log its fingerprint.
- `NOPASSWD: ALL` is powerful, and the apt upgrade runs through `env`, so a narrower sudoers rule is not much safer in practice. Protect the account and key accordingly.
- No passphrase-protected keys and no reauthentication flow yet.
- macOS and the BSDs are not supported. Hardware sensors read `/proc` and `/sys`, so they are Linux-only as well.
- Each hardware poll opens a new SSH connection, which shows up in the host's auth log once per interval.

## Roadmap

- A reboot-required sensor
- More platforms (FreeBSD `pkg`, macOS `softwareupdate`)

## License

GPL-3.0, see [LICENSE](LICENSE).
