# Flashing of ESP32 node firmware packages via esptool

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import zipfile
import requests
try:
    from util.SerialPortInfo import port_present as port_present_fn
except ImportError:
    def port_present_fn(port, wait_secs=0):
        return True

ESPTOOL_MIN_VERSION = "4.8.1"  # first version with ESP32-C5 support
ESPTOOL_REQ_STR = "esptool>=" + ESPTOOL_MIN_VERSION
MAX_PACKAGE_SIZE = 8000000
MANIFEST_NAME = "manifest.json"
ESPTOOL_ATTEMPTS = 3  # esptool runs, while it fails before writing to flash
ESPTOOL_RETRY_DELAY_SECS = 1.0
ESPTOOL_WRITE_PREFIXES = ("Writing at", "Wrote ")  # esptool output once writing to flash has started
ESPTOOL_CONNECTED_PREFIXES = ("Connected to", "Chip is", "Detecting chip type")  # (v5, v4) once connected
ESPTOOL_PART_START_PREFIXES = ("Writing '", "Compressed ")  # esptool output at the start of each part
ESPTOOL_PROGRESS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
ESPTOOL_PROGRESS_STEP_PCT = 25.0  # write progress shown about every this many percent
PORT_WAIT_SECS = 5.0  # time to wait for a missing serial port to appear
DOWNLOAD_HEADERS ={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:87.0) Gecko/20100101 Firefox/87.0"}

# firmware package: .zip file with 'manifest.json' (ESP Web Tools format) and the parts it lists
class FwPackage:
    def __init__(self, name, version, date, chip_family, parts):
        self.name = name
        self.version = version
        self.date = date
        self.chip_family = chip_family
        self.parts = parts  # list of (offset, path, data)

    def chip_arg(self):
        return self.chip_family.lower().replace("-", "")

    def total_size(self):
        return sum(len(p[2]) for p in self.parts)

    def summary_str(self):
        return "{} {}{}, {}".format(self.name, self.version, \
                                    (" (" + self.date + ")") if self.date else "", self.chip_family)

# returns True if given source string names a firmware package (.zip file)
def is_fw_package_src(src_str):
    return bool(src_str) and src_str.strip().lower().endswith(".zip")

# reads given source (URL or local file) to bytes
def load_package_data(src_str):
    src_str = src_str.strip()
    if src_str.startswith("http://") or src_str.startswith("https://"):
        resp = requests.get(src_str, headers=DOWNLOAD_HEADERS, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError("Error reading file data, HTTP status code: {}".format(resp.status_code))
        data = resp.content
    else:
        with open(src_str, "rb") as file_obj:
            data = file_obj.read(MAX_PACKAGE_SIZE + 1)
    if len(data) <= 0:
        raise RuntimeError("File data size is zero")
    if len(data) > MAX_PACKAGE_SIZE:
        raise RuntimeError("File data size too large")
    return data

# parses firmware package data, checks part sizes and sha256 values, returns FwPackage
def parse_package(data, chip_family=None):
    try:
        zip_obj = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise RuntimeError("File is not a valid .zip file")
    with zip_obj:
        try:
            manifest = json.loads(zip_obj.read(MANIFEST_NAME).decode("utf-8"))
        except KeyError:
            raise RuntimeError("No '{}' found in .zip file".format(MANIFEST_NAME))
        builds = manifest.get("builds") or []
        if chip_family:
            builds = [b for b in builds if str(b.get("chipFamily", "")).lower() == chip_family.lower()]
        if not builds:
            raise RuntimeError("No matching build found in '{}'".format(MANIFEST_NAME))
        build = builds[0]
        build_chip = str(build.get("chipFamily", ""))
        if not build_chip.upper().startswith("ESP32"):
            raise RuntimeError("Unsupported chip family: '{}'".format(build_chip))
        parts = []
        for part in build.get("parts") or []:
            path = part.get("path")
            offset = part.get("offset")
            if not path or not isinstance(offset, int) or offset < 0:
                raise RuntimeError("Invalid part entry in '{}'".format(MANIFEST_NAME))
            try:
                part_data = zip_obj.read(path)
            except KeyError:
                raise RuntimeError("Part file '{}' not found in .zip file".format(path))
            if "size" in part and part["size"] != len(part_data):
                raise RuntimeError("Size mismatch for part file '{}'".format(path))
            if "sha256" in part and \
                    hashlib.sha256(part_data).hexdigest().lower() != str(part["sha256"]).lower():
                raise RuntimeError("SHA-256 mismatch for part file '{}'".format(path))
            parts.append((offset, path, part_data))
        if not parts:
            raise RuntimeError("No parts listed for build in '{}'".format(MANIFEST_NAME))
        return FwPackage(str(manifest.get("name", "")), str(manifest.get("version", "")), \
                         str(manifest.get("date", "")), build_chip, parts)

# loads and parses firmware package from given source (URL or local file)
def load_package(src_str, chip_family=None):
    return parse_package(load_package_data(src_str), chip_family)

def _version_tuple(ver_str):
    nums = []
    for item in str(ver_str).split("."):
        digits = ""
        for ch in item:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        nums.append(int(digits))
        if len(nums) >= 3:
            break
    return tuple(nums)

# returns version string of installed esptool, or None if not installed
def get_esptool_version():
    try:
        import importlib.metadata
        return importlib.metadata.version("esptool")
    except Exception:
        return None

# returns True if esptool needs to be installed (or upgraded) before flashing
def esptool_needs_install():
    ver_str = get_esptool_version()
    return (not ver_str) or _version_tuple(ver_str) < _version_tuple(ESPTOOL_MIN_VERSION)

# runs given command and sends its output lines to given function; returns exit code
def _run_cmd(args, output_fn):
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, \
                            stdin=subprocess.DEVNULL, env=env)
    for line in iter(proc.stdout.readline, b''):
        text = line.decode("utf-8", errors="replace").rstrip("\r\n")
        text = text.split("\r")[-1].rstrip()  # keep last part of overwritten progress line
        if text:
            output_fn(text)
    proc.stdout.close()
    return proc.wait()

# returns pip constraint lines that pin installed packages (other than esptool) at their current versions
def installed_package_constraints():
    import importlib.metadata
    versions = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name")
        if name and dist.version:
            key = name.lower().replace("_", "-").replace(".", "-")
            if key != "esptool" and key not in versions:
                versions[key] = "{}=={}".format(name, dist.version)
    return sorted(versions.values(), key=str.lower)

# installs esptool into the Python environment running the server, without changing
#  installed packages (files of loaded modules can't be replaced on Windows); returns True if successful
def install_esptool(output_fn):
    output_fn("Installing {} via pip".format(ESPTOOL_REQ_STR))
    with tempfile.TemporaryDirectory(prefix="rh_esptool_") as tmp_dir:
        constraints_file = os.path.join(tmp_dir, "constraints.txt")
        with open(constraints_file, "w") as file_obj:
            file_obj.write("\n".join(installed_package_constraints()) + "\n")
        ret_val = _run_cmd([sys.executable, "-m", "pip", "install", "--upgrade", \
                            "-c", constraints_file, ESPTOOL_REQ_STR], output_fn)
    if ret_val != 0:
        output_fn("Install of esptool failed (exit code {})".format(ret_val))
        return False
    if esptool_needs_install():
        output_fn("Install of esptool did not provide version {} or later".format(ESPTOOL_MIN_VERSION))
        return False
    output_fn("Installed esptool version {}".format(get_esptool_version()))
    return True

# returns esptool arguments for writing the given package to flash (esptool v5 or v4 syntax)
def build_esptool_args(port_str, package, part_files, esptool_ver_str):
    v5_flag = _version_tuple(esptool_ver_str) >= (5,)
    args = ["--chip", package.chip_arg(), "--port", port_str, \
            "--before", "default-reset" if v5_flag else "default_reset", \
            "--after", "hard-reset" if v5_flag else "hard_reset", \
            "write-flash" if v5_flag else "write_flash"]
    for (offset, _path, _data), file_str in zip(package.parts, part_files):
        args += ["0x{:x}".format(offset), file_str]
    return args

# shapes esptool output for display: the output of an attempt is held until connected to the chip (so a failed
#  connection attempt can be shown as one line), write progress is shown about every 25 %, and temporary
#  part-file paths are shown as part names
class EsptoolOutputFilter:
    def __init__(self, output_fn, path_names=None):
        self.output_fn = output_fn
        self.path_names = path_names or {}
        self.held = []
        self.connected = False
        self.write_started = False
        self.next_pct = 0.0

    def __call__(self, text):
        for path, name in self.path_names.items():
            text = text.replace(path, name)
        if text.startswith(ESPTOOL_WRITE_PREFIXES):
            self.write_started = True
        if not self.connected:
            self.held.append(text)
            if text.startswith(ESPTOOL_CONNECTED_PREFIXES):
                self.connected = True
                self.show_held()
            return
        if text.startswith(ESPTOOL_PART_START_PREFIXES):
            self.next_pct = 0.0  # (progress of next part)
        elif text.startswith("Writing at"):
            match = ESPTOOL_PROGRESS_RE.search(text)
            if match:
                pct = float(match.group(1))
                if pct < self.next_pct and pct < 100.0:
                    return
                self.next_pct = (int(pct // ESPTOOL_PROGRESS_STEP_PCT) + 1) * ESPTOOL_PROGRESS_STEP_PCT
        self.output_fn(text)

    def show_held(self):
        for line in self.held:
            self.output_fn(line)
        self.held = []

    # returns the line of held output that best describes the error
    def error_summary(self):
        for line in reversed(self.held):
            if line.upper().startswith(("ERROR", "A FATAL ERROR")):
                return line
        for line in reversed(self.held):
            if "error" in line.lower() and not line.startswith("Note"):
                return line
        return self.held[-1] if self.held else ""

# writes given firmware package to the ESP32 at the given serial port; returns True if successful
def flash_package(port_str, package, output_fn):
    esptool_ver = get_esptool_version()
    if esptool_needs_install():
        output_fn("esptool version {} or later is required".format(ESPTOOL_MIN_VERSION))
        return False
    output_fn("Using esptool version {}, port {}".format(esptool_ver, port_str))
    with tempfile.TemporaryDirectory(prefix="rh_esp32fw_") as tmp_dir:
        part_files = []
        for idx, (_offset, path, data) in enumerate(package.parts):
            file_str = os.path.join(tmp_dir, "{}_{}".format(idx, os.path.basename(path)))
            with open(file_str, "wb") as file_obj:
                file_obj.write(data)
            part_files.append(file_str)
        args = build_esptool_args(port_str, package, part_files, esptool_ver)
        path_names = {file_str: os.path.basename(path) for file_str, (_offset, path, _data) in \
                      zip(part_files, package.parts)}
        for attempt in range(1, ESPTOOL_ATTEMPTS + 1):
            # an ESP32 without firmware keeps restarting, so its USB port comes and goes
            if not port_present_fn(port_str, PORT_WAIT_SECS):
                output_fn("Serial port {} not present".format(port_str))
            output_filter = EsptoolOutputFilter(output_fn, path_names)
            ret_val = _run_cmd([sys.executable, "-m", "esptool"] + args, output_filter)
            if ret_val == 0:
                output_filter.show_held()
                return True
            if output_filter.write_started or attempt >= ESPTOOL_ATTEMPTS:
                output_filter.show_held()  # (no retry once writing to flash has started)
                output_fn("esptool failed (exit code {})".format(ret_val))
                return False
            output_fn("Attempt {} of {} failed{}; retrying".format(attempt, ESPTOOL_ATTEMPTS, \
                      (": " + output_filter.error_summary()) if not output_filter.connected else ""))
            time.sleep(ESPTOOL_RETRY_DELAY_SECS)
    return False
