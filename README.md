# Unix Device Manager for Home Assistant

Monitor and update Linux/unix hosts from Home Assistant over SSH. Nothing needs to be installed on the remote device.

## Features

- **Sensors**
  - **OS version**, read from `/etc/os-release`.
  - **Updates available**: the count of pending updates, with the package names in a `packages` attribute (capped at 50).
  - **IP address** (diagnostic).
- **Device info**: manufacturer, model, OS version (shown as the device's software version), architecture (hardware version) and MAC address. Hardware details come from firmware data on x86 and VMs, or the device tree on Raspberry Pi and other ARM boards.
- **Buttons**: **Update repositories** and **Update OS**. Sensors refresh after either one runs.
- **Package managers**: apt, dnf, yum, apk, pacman (via `checkupdates` from `pacman-contrib`) and zypper, auto-detected.
- **Options**: update check interval (default 60 minutes, 5 to 1440).

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

### Optional: restrict the key

Prefix the key's line in `authorized_keys` so it only works from your Home Assistant machine:

```
from="192.168.1.0/24",no-port-forwarding,no-agent-forwarding,no-X11-forwarding ssh-ed25519 AAAA... ha-unix-manager
```

Use an IP or CIDR range, not a hostname. If logins start failing, check `journalctl -u ssh` on the remote device: a mismatch logs "Authentication tried for ... with correct key but not from a permitted host" along with the address sshd saw.

## Notes and limitations

- **Update OS** runs the normal package upgrade (for example `apt-get upgrade`), not a distribution release upgrade. The button waits for it to finish, up to an hour, and reports failures in the UI.
- Refresh and upgrade commands run under `nohup`, so a dropped SSH connection cannot kill a package manager mid-transaction. Only one operation runs per host at a time.
- **Host key verification is currently disabled.** Pinning host keys is planned and is the most important hardening step.
- `NOPASSWD: ALL` is powerful, and the apt upgrade runs through `env`, so a narrower sudoers rule is not much safer in practice. Protect the account and key accordingly.
- No passphrase-protected keys and no reauthentication flow yet.
- macOS and the BSDs are not supported.

## Roadmap

- A native `update` entity
- A reboot-required sensor
- Host key pinning
- More platforms (FreeBSD `pkg`, macOS `softwareupdate`)

## License

GPL-3.0, see [LICENSE](LICENSE).
