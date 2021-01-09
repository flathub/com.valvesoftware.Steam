#!/usr/bin/python3
import os
import os.path
import sys
import shutil
import errno
import fnmatch
import configparser
from distutils.version import LooseVersion


STEAM_PATH = "/app/bin/steam"
FLATPAK_STATE_DIR = os.path.expandvars("$HOME/.var/app/com.valvesoftware.Steam")
XDG_DATA_HOME = os.environ["XDG_DATA_HOME"]
XDG_CACHE_HOME = os.environ["XDG_CACHE_HOME"]
XDG_RUNTIME_DIR = os.environ["XDG_RUNTIME_DIR"]
DEFAULT_CONFIG_DIR = ".config"
DEFAULT_DATA_DIR = ".local/share"
DEFAULT_CACHE_DIR = ".cache"
FLATPAK_INFO = "/.flatpak-info"


def read_flatpak_info(path):
    flatpak_info = configparser.ConfigParser()
    with open(path) as f:
        flatpak_info.read_file(f)
    return {
        "flatpak-version": flatpak_info.get("Instance", "flatpak-version"),
        "runtime-path": flatpak_info.get("Instance", "runtime-path"),
        "app-extensions": dict((s.split("=")
                                for s in flatpak_info.get("Instance", "app-extensions",
                                                          fallback="").split(";") if s)),
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


def symlink_rel(target, source):
    assert os.path.isabs(source)
    assert os.path.isabs(target)
    rel_target = os.path.relpath(target, os.path.dirname(source))
    os.symlink(rel_target, source)


def check_bad_filesystem_entries(entries):
    bad_names = ["home",
                 "host",
                 os.path.expandvars("/var/home/$USER"),
                 os.path.expandvars("/home/$USER")]
    found = False
    for entry in entries:
        items = entry.split(";")
        if items[0] in bad_names:
            print (f"Bad item \"{items[0]}\" found in filesystem overrides")
            found = True
    if found:
        faq = ("https://github.com/flathub/com.valvesoftware.Steam/wiki"
               "#i-want-to-add-external-disk-for-steam-libraries")
        raise SystemExit(f"Please see {faq}")


def check_allowed_to_run(current_info):
    current_version = current_info["flatpak-version"]
    required = "1.0.0"
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
    source = os.path.expandvars("$XDG_CONFIG_HOME")
    target = os.path.join(FLATPAK_STATE_DIR, DEFAULT_CONFIG_DIR)
    backup = f'{target}.bak'
    relocated = os.path.expandvars("$XDG_CONFIG_HOME.old")
    if not os.path.islink(source):
        if os.path.isdir(target):
            copytree(target, backup)
        copytree(source, target)
        os.rename(source, relocated)
        symlink_rel(target, source)
    else:
        if os.path.isdir(relocated):
            shutil.rmtree(relocated)
    os.environ["XDG_CONFIG_HOME"] = os.path.expandvars(f"$HOME/{DEFAULT_CONFIG_DIR}")


def migrate_data():
    """
    Data directory contains a directory Steam which contains all installed
    games and is massive. It needs to be separately moved
    """
    source = os.path.expandvars("$XDG_DATA_HOME")
    target = os.path.join(FLATPAK_STATE_DIR, DEFAULT_DATA_DIR)
    backup = f'{target}.bak'
    steam_root_source = os.path.join(source, "Steam")
    steam_root_target = os.path.join(target, "Steam")
    if not os.path.islink(source):
        if os.path.isdir(target):
            copytree(target, backup, ignore=[steam_root_target])
        copytree(source, target, ignore=[steam_root_source])
        if os.path.isdir(steam_root_source):
            os.rename(steam_root_source, steam_root_target)
        shutil.rmtree(source)
        symlink_rel(target, source)
    os.environ["XDG_DATA_HOME"] = os.path.expandvars(f"$HOME/{DEFAULT_DATA_DIR}")


def migrate_cache():
    source = os.path.expandvars("$XDG_CACHE_HOME")
    target = os.path.join(FLATPAK_STATE_DIR, DEFAULT_CACHE_DIR)
    if not os.path.islink(source):
        copytree(source, target)
        shutil.rmtree(source)
        symlink_rel(target, source)
    os.environ["XDG_CACHE_HOME"] = os.path.expandvars(f"$HOME/{DEFAULT_CACHE_DIR}")


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


def configure_shared_library_guard():
    mode = int(os.environ.get("SHARED_LIBRARY_GUARD", 1))
    if not mode:
        return
    else:
        os.environ["LD_AUDIT"] = f"/app/links/$LIB/libshared-library-guard.so"


def main(steam_binary=STEAM_PATH):
    os.chdir(os.environ["HOME"]) # Ensure sane cwd
    print ("https://github.com/flathub/com.valvesoftware.Steam/wiki")
    current_info = read_flatpak_info(FLATPAK_INFO)
    check_allowed_to_run(current_info)
    migrate_config()
    migrate_data()
    migrate_cache()
    timezone_workaround()
    configure_shared_library_guard()
    enable_discord_rpc()
    os.execv(steam_binary, [steam_binary] + sys.argv[1:])
