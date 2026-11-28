'''
Serial-port discovery for the "List Ports" function on the Advanced Settings page.

Lists the serial ports visible to the server process on Linux, macOS and Windows,
together with stable alias names (e.g. /dev/serial/by-id/... on Linux) and an
access check so operators can spot permission problems.

Ports are never opened here: opening a port toggles DTR on many USB-serial
adapters, which resets Arduino-based nodes.
'''

import os
import re
import sys
import time
import logging

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform.startswith('win')
IS_MACOS = sys.platform == 'darwin'

LINUX_ALIAS_DIRS = ('/dev/serial/by-id', '/dev/serial/by-path')
# tty device-name prefixes that may be serial ports (used to filter /dev symlinks)
POSIX_TTY_PREFIXES = ('tty', 'cu.', 'rfcomm', 'serial')


def _norm_key(path):
    '''Returns a key for comparing port names (resolves symlinks on POSIX).'''
    if not path:
        return ''
    path = str(path).strip()
    if IS_WINDOWS:
        path = path.upper()
        if path.startswith('\\\\.\\'):
            path = path[4:]
        return path
    try:
        return os.path.realpath(path)
    except Exception:
        return path


def _collect_posix_aliases():
    '''Returns {real_device_path: [alias, ...]} for serial-port symlinks.'''
    aliases = {}

    def add(link_path):
        try:
            if os.path.islink(link_path):
                target = os.path.realpath(link_path)
                if os.path.basename(target).startswith(POSIX_TTY_PREFIXES):
                    aliases.setdefault(target, [])
                    if link_path not in aliases[target]:
                        aliases[target].append(link_path)
        except Exception:
            pass

    # stable udev names first (preferred for configuration)
    for alias_dir in LINUX_ALIAS_DIRS:
        try:
            for name in sorted(os.listdir(alias_dir)):
                add(os.path.join(alias_dir, name))
        except OSError:
            pass
    # other symlinks directly in /dev (e.g. /dev/serial0 on Raspberry Pi, custom udev rules)
    try:
        for entry in sorted(os.scandir('/dev'), key=lambda e: e.name):
            if entry.is_symlink():
                add(entry.path)
    except OSError:
        pass
    return aliases


def _posix_access_info(device):
    info = {'access': 'unknown'}
    try:
        import stat
        st = os.stat(device)
        info['mode'] = stat.filemode(st.st_mode)
        try:
            import pwd
            info['owner'] = pwd.getpwuid(st.st_uid).pw_name
        except Exception:
            info['owner'] = str(st.st_uid)
        try:
            import grp
            info['group'] = grp.getgrgid(st.st_gid).gr_name
        except Exception:
            info['group'] = str(st.st_gid)
        info['access'] = 'ok' if os.access(device, os.R_OK | os.W_OK) else 'denied'
    except FileNotFoundError:
        info['access'] = 'missing'
    except Exception as ex:
        info['access_error'] = str(ex)
    return info


def _process_info():
    info = {'platform': sys.platform}
    try:
        if IS_WINDOWS:
            import getpass
            info['user'] = getpass.getuser()
        else:
            import pwd
            import grp
            info['user'] = pwd.getpwuid(os.geteuid()).pw_name
            names = []
            for gid in sorted(set(os.getgroups() + [os.getegid()])):
                try:
                    names.append(grp.getgrgid(gid).gr_name)
                except Exception:
                    names.append(str(gid))
            info['groups'] = names
    except Exception as ex:
        logger.debug("Unable to determine process user/groups: {}".format(ex))
    return info


ESPRESSIF_USB_VID = 0x303A
# an ESP32 without firmware keeps restarting, so its USB port comes and goes every second or so
RECENT_ESPRESSIF_SECS = 30.0  # time an Espressif port seen is expected to be present again
PORT_RECHECK_SECS = 2.0  # time to keep checking for a port that is expected but missing
PORT_RECHECK_INTERVAL_SECS = 0.2

_recent_espressif_ports = {}  # port key -> time the Espressif port was last seen


def _comports():
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    # include_links=False: aliases are collected separately so each device appears once
    port_infos = list(list_ports.comports())
    now = time.monotonic()
    for port_info in port_infos:
        if getattr(port_info, 'vid', None) == ESPRESSIF_USB_VID:
            _recent_espressif_ports[_norm_key(port_info.device)] = now
    return port_infos


def _comports_with_recheck():
    '''Returns the serial ports (as _comports()); if an Espressif port seen recently is missing,
       checks again for a short time and adds it if it appears'''
    port_infos = _comports()
    if port_infos is None:
        return None
    found = {_norm_key(p.device): p for p in port_infos}
    deadline = time.monotonic() + PORT_RECHECK_SECS
    while True:
        now = time.monotonic()
        missing = [key for key, seen_time in _recent_espressif_ports.items() \
                   if now - seen_time < RECENT_ESPRESSIF_SECS and key not in found]
        if not missing or now >= deadline:
            break
        time.sleep(PORT_RECHECK_INTERVAL_SECS)
        for port_info in _comports() or []:
            found.setdefault(_norm_key(port_info.device), port_info)
    return list(found.values())


def _port_present_now(port):
    if not IS_WINDOWS:
        return bool(port) and os.path.exists(str(port).strip())
    try:
        port_infos = _comports()
    except Exception:
        return False
    return bool(port_infos) and _norm_key(port) in (_norm_key(p.device) for p in port_infos)


def port_present(port, wait_secs=0):
    '''Returns True if the given serial port currently exists (without opening it); if 'wait_secs'
       is given, a missing port is checked again for up to that time (for a port that comes and goes).'''
    deadline = time.monotonic() + wait_secs
    while True:
        if _port_present_now(port):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(PORT_RECHECK_INTERVAL_SECS)


def is_espressif_usb_port(port, wait_secs=0):
    '''Returns True if the given serial port is the native USB port of an Espressif chip (such as an ESP32-C5),
       without opening it; if 'wait_secs' is given, a missing port is checked again for up to that time.'''
    deadline = time.monotonic() + wait_secs
    while True:
        try:
            port_infos = _comports()
        except Exception:
            return False
        key = _norm_key(port)  # (each time, as an alias such as /dev/serial/by-id/... resolves only while present)
        for port_info in port_infos or []:
            if _norm_key(port_info.device) == key:
                return getattr(port_info, 'vid', None) == ESPRESSIF_USB_VID
        if time.monotonic() >= deadline:
            return False
        time.sleep(PORT_RECHECK_INTERVAL_SECS)


def list_serial_ports(configured_ports=None):
    '''
    Returns a dict describing the serial ports available to this process:
      platform, user, groups (POSIX), pyserial (bool), ports (list), configured_missing (list)
    Each port entry: device, recommended, aliases, description, hwid, manufacturer,
      product, serial_number, vid, pid, location, access, owner, group, mode, configured
    '''
    configured_ports = [p for p in (configured_ports or []) if p]
    configured_keys = {_norm_key(p): p for p in configured_ports}

    result = _process_info()
    port_infos = _comports_with_recheck()
    result['pyserial'] = port_infos is not None
    port_infos = port_infos or []

    aliases = {} if IS_WINDOWS else _collect_posix_aliases()

    ports = []
    seen = set()

    def make_entry(device, pinfo=None):
        key = _norm_key(device)
        entry = {
            'device': device,
            'aliases': [],
            'description': None,
            'hwid': None,
            'manufacturer': None,
            'product': None,
            'serial_number': None,
            'vid': None,
            'pid': None,
            'location': None,
        }
        if pinfo is not None:
            desc = getattr(pinfo, 'description', None)
            entry['description'] = desc if desc and desc != 'n/a' else None
            hwid = getattr(pinfo, 'hwid', None)
            entry['hwid'] = hwid if hwid and hwid != 'n/a' else None
            for attr in ('manufacturer', 'product', 'serial_number', 'location'):
                entry[attr] = getattr(pinfo, attr, None)
            vid = getattr(pinfo, 'vid', None)
            pid = getattr(pinfo, 'pid', None)
            entry['vid'] = '{:04X}'.format(vid) if vid is not None else None
            entry['pid'] = '{:04X}'.format(pid) if pid is not None else None

        if IS_WINDOWS:
            entry['access'] = 'unknown'
        else:
            entry['aliases'] = list(aliases.get(key, []))
            if IS_MACOS and os.path.basename(device).startswith('cu.'):
                tty_twin = os.path.join(os.path.dirname(device), 'tty.' + os.path.basename(device)[3:])
                if os.path.exists(tty_twin):
                    entry['aliases'].append(tty_twin)
            entry.update(_posix_access_info(device))

        # recommended name: by-id alias when the device has a serial number, then by-path,
        # then by-id, then /dev/serialN (Raspberry Pi), else device
        by_id = [a for a in entry['aliases'] if a.startswith('/dev/serial/by-id/')]
        by_path = [a for a in entry['aliases'] if a.startswith('/dev/serial/by-path/')]
        serial_n = [a for a in entry['aliases'] if re.fullmatch(r'/dev/serial\d+', a)]
        if by_id and entry['serial_number']:
            recommended = by_id[0]
        elif by_path:
            recommended = by_path[0]
        elif by_id:
            recommended = by_id[0]
        elif serial_n:
            recommended = serial_n[0]
        else:
            recommended = device
        entry['recommended'] = recommended

        matched = [cfg for cfg_key, cfg in configured_keys.items() if cfg_key == key]
        entry['configured'] = matched[0] if matched else None
        seen.add(key)
        return entry

    for pinfo in port_infos:
        dev = getattr(pinfo, 'device', None)
        if dev and _norm_key(dev) not in seen:
            ports.append(make_entry(dev, pinfo))

    # Linux: pyserial skips some on-board UARTs (e.g. /dev/ttyS0 behind /dev/serial0 on
    # Raspberry Pi); include any aliased tty device that is not yet listed
    if not IS_WINDOWS:
        for target in sorted(aliases.keys()):
            if target not in seen and os.path.exists(target):
                ports.append(make_entry(target))

    ports.sort(key=lambda p: p['device'])
    result['ports'] = ports
    result['configured_missing'] = [cfg for cfg_key, cfg in configured_keys.items() if cfg_key not in seen]
    return result


if __name__ == '__main__':
    import json
    print(json.dumps(list_serial_ports(sys.argv[1:]), indent=2))
