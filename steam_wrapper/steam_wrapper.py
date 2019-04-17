#!/usr/bin/python3
import os
import os.path
import stat
import sys
import shutil
import errno
import fnmatch
import subprocess
import configparser
from pathlib import Path
from distutils.version import LooseVersion


STEAM_PATH = "/app/bin/steam"
STEAM_ROOT = os.path.expandvars("$HOME/.var/app/com.valvesoftware.Steam")
XDG_DATA_HOME = os.environ["XDG_DATA_HOME"]
XDG_CACHE_HOME = os.environ["XDG_CACHE_HOME"]
XDG_RUNTIME_DIR = os.environ["XDG_RUNTIME_DIR"]
CONFIG = ".config"
DATA = ".local/share"
CACHE = ".cache"
FLATPAK_INFO = "/.flatpak-info"


def read_flatpak_info(path):
    flatpak_info = configparser.ConfigParser()
    with open(path) as f:
        flatpak_info.read_file(f)
    return {
        "flatpak-version": flatpak_info.get("Instance", "flatpak-version"),
        "runtime-path": flatpak_info.get("Instance", "runtime-path"),
        "app-extensions": flatpak_info.get("Instance", "app-extensions",
                                           fallback=None),
        "runtime-extensions": flatpak_info.get("Instance",
                                               "runtime-extensions",
                                               fallback=None),
        "filesystems": flatpak_info.get("Context", "filesystems",
                                        fallback="").split(";")
    }

def read_file(path):
    try:
        with open(path, "r") as f:
            return f.read()
    except IOError as e:
        if e.errno == errno.ENOENT:
            return ""
        raise

def timezone_workaround():
    if os.environ.get("TZ"):
        return
    zone_name = read_file("/etc/timezone").rstrip()
    if zone_name and os.path.exists(f"/usr/share/zoneinfo/{zone_name}"):
        os.environ["TZ"] = zone_name
        print (f"Overriding TZ to {zone_name}")

def prompt():
    p = subprocess.Popen(["zenity", "--question",
                          ("--text="
                           "This is com.valvesoftware.Steam cloud sync repair. "
                           "If you have conflicting local and cloud data for "
                           "your game, this may result in partial loss of your "
                           "cloud data. If you instead prefer ensuring cloud data "
                           "persists, please relocate your "
                           "~/.var/app/com.valvesoftware.Steam/data/Steam "
                           "to a secure location, "
                           "remove ~/.var/app/com.valvesoftware.Steam "
                           "and put Steam data directory back to avoid needing to "
                           "re-download games. Do you want to allow the migration?")])
    return p.wait() == 0

def ignored(name, patterns):
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
    else:
        return False

def filter_names(root, names, patterns):
    _names = []
    for name in names:
        if not ignored(os.path.join(root, name), patterns):
            _names.append(name)
    return _names

def try_create(path):
    try:
        os.mkdir(path)
    except FileExistsError:
        pass

def copytree(source, target, ignore=None):
    os.makedirs(target, exist_ok=True)
    for root, d_names, f_names in os.walk(source):
        rel_root = os.path.relpath(root, source)
        target_root = os.path.normpath(os.path.join(target, rel_root))
        try_create(target_root)
        if ignore:
            d_names[:] = filter_names(root, d_names, ignore)
            f_names = filter_names(root, f_names, ignore)
        for f_name in f_names:
            full_source = os.path.join(root, f_name)
            full_target = os.path.join(target_root, f_name)
            print (f"Relocating {full_source} to {full_target}")
            shutil.copy2(full_source, full_target)
            os.utime(full_target)

def check_nonempty(name):
    try:
        with open(name) as file:
            return len(file.read()) > 0
    except IOError as e:
        if e.errno != errno.ENOENT:
            raise
        else:
            return False

def check_bad_filesystem_entries(entries):
    bad_names = ["home", "host", os.path.expandvars("/var/home/$USER"),
         "/home/$USER"]
    found = False
    for entry in entries:
        items = entry.split(";")
        if items[0] in bad_names:
            print (f"Bad item \"{items[0]}\" found in filesystem overrides")
            found = True
    if found:
        faq = ("https://github.com/flathub/com.valvesoftware.Steam/wiki/"
               "Frequently-asked-questions#i-want-to-add-external-disk-for-steam-libraries")
        raise SystemExit(f"Please see {faq}")

def check_allowed_to_run():
    current_info = read_flatpak_info(FLATPAK_INFO)
    current_version = current_info["flatpak-version"]
    required = "0.10.3"
    if LooseVersion(current_version) < LooseVersion(required):
        raise SystemExit(f"Flatpak {required} or newer required")

    check_bad_filesystem_entries(current_info["filesystems"])

    steam_home = os.path.expandvars("$HOME/.var/app/com.valvesoftware.Steam/home")
    if os.path.isdir(steam_home):
        # Relocate from old migration
        ignore = ("*/.steam", "*/.local", "*/.var")
        copytree(steam_home, os.path.expandvars("$HOME"), ignore=ignore)
        shutil.rmtree(steam_home)


def migrate_config():
    """
    There's bind-mounted contents inside config dir so we need to
    1) Relocate, move to temp
    2) Next start of app, remove temp
    In theory this should not break everything
    """
    consent = True
    source = os.path.expandvars("$XDG_CONFIG_HOME")
    target = CONFIG
    relocated = os.path.expandvars("$XDG_CONFIG_HOME.old")
    if not os.path.islink(source):
        if os.path.isdir(target):
            consent = prompt()
            if not consent:
                return consent
        copytree(source, target)
        os.rename(source, relocated)
        os.symlink(target, source)
    else:
        if os.path.isdir(relocated):
            shutil.rmtree(relocated)
    os.environ["XDG_CONFIG_HOME"] = os.path.expandvars(f"$HOME/{CONFIG}")
    return consent

def migrate_data():
    """
    Data directory contains a directory Steam which contains all installed
    games and is massive. It needs to be separately moved
    """
    source = os.path.expandvars("$XDG_DATA_HOME")
    target = DATA
    steam_home = os.path.join(source, "Steam")
    xdg_data_home = os.path.join(STEAM_ROOT, target)
    if not os.path.islink(source):
        copytree(source, target, ignore=[steam_home])
        if os.path.isdir(steam_home):
            os.rename(steam_home,
                      os.path.join(xdg_data_home, "Steam"))
        shutil.rmtree(source)
        os.symlink(target, source)
    os.environ["XDG_DATA_HOME"] = os.path.expandvars(f"$HOME/{DATA}")

def migrate_cache():
    source = os.path.expandvars("$XDG_CACHE_HOME")
    target = CACHE
    if not os.path.islink(source):
        copytree(source, target)
        shutil.rmtree(source)
        os.symlink(target, source)
    os.environ["XDG_CACHE_HOME"] = os.path.expandvars(f"$HOME/{CACHE}")

def enable_discord_rpc():
    # Discord can have a socket numbered from 0 to 9
    for i in range(10):
        rpc_socket = f"discord-ipc-{i}"
        src_rel = os.path.join("app", "com.discordapp.Discord", rpc_socket)
        dst = os.path.join(XDG_RUNTIME_DIR, rpc_socket)
        if os.path.exists(dst) or os.path.islink(dst):
            continue
        else:
            os.symlink(src=src_rel, dst=dst)

def repair_broken_migration():
    cache = CACHE
    wrong_data = ".data"
    wrong_cache = DATA
    data = wrong_cache
    root = os.path.realpath(STEAM_ROOT)
    current_cache = os.path.relpath(os.path.realpath(XDG_CACHE_HOME), root)
    current_data = os.path.relpath(os.path.realpath(XDG_DATA_HOME), root)
    if os.path.islink(XDG_CACHE_HOME) and current_cache == wrong_cache:
        copytree(current_cache, cache)
        os.unlink(XDG_CACHE_HOME)
        os.symlink(cache, XDG_CACHE_HOME)
    if os.path.islink(XDG_DATA_HOME) and current_data == wrong_data:
        steam_home = os.path.join(current_data, "Steam")
        copytree(current_data, data, [steam_home])
        if os.path.isdir(steam_home):
            os.rename(steam_home,
                      os.path.join(data, "Steam"))
        os.unlink(XDG_DATA_HOME)
        os.symlink(data, XDG_DATA_HOME)
        shutil.rmtree(wrong_data)

def configure_shared_library_guard():
    mode = int(os.environ.get("SHARED_LIBRARY_GUARD", 0))
    if not mode:
        return
    else:
        library = "libshared-library-guard.so"
        os.environ["LD_AUDIT"] = os.pathsep.join((f"/usr/lib/x86_64-linux-gnu/{library}",
                                                  f"/app/lib/i386-linux-gnu/{library}"))
        if mode > 1:
            os.environ["LD_BIND_NOW"] = "1"

def setup_proton_extensions():
    # Create root symlink if it doesn't exist
    src = STEAM_ROOT + '/.local/share/Steam'
    dst = STEAM_ROOT + '/.steam/root'
    proton_dest = src + '/compatibilitytools.d'

    # If directory doesn't exist, make it
    if not os.path.isdir(os.path.dirname(dst)):
        os.makedirs(os.path.dirname(dst))
    # If directory doesn't exist, symlink it
    if not os.path.isdir(os.path.dirname(src)):
        os.symlink(src, dst)

    # Try to create folder if it doesn't exist
    os.makedirs(proton_dest, exist_ok=True)

    # Copy extensions if they exist
    subfolders = [f.path for f in os.scandir("/app/proton") if f.is_dir() ]
    subfolders_names = [f.name for f in os.scandir("/app/proton") if f.is_dir() ]

    for proton, proton_name in zip(subfolders, subfolders_names):
        proton_real_dest = proton_dest + "/" + proton_name
        p = Path(proton_real_dest)

        if p.exists():
            shutil.rmtree(proton_real_dest)
        shutil.copytree(proton, proton_real_dest)

def main(steam_binary=STEAM_PATH):
    os.chdir(os.environ["HOME"]) # Ensure sane cwd
    print ("https://github.com/flathub/com.valvesoftware.Steam/wiki/Frequently-asked-questions")
    check_allowed_to_run()
    consent = migrate_config()
    if consent:
        migrate_data()
        migrate_cache()
    repair_broken_migration()
    timezone_workaround()
    configure_shared_library_guard()
    enable_discord_rpc()
    setup_proton_extensions()
    os.execve(steam_binary, [steam_binary] + sys.argv[1:], os.environ)
