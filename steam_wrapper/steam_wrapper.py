#!/usr/bin/python3
import os
import os.path
import sys
import shutil
import errno
import fnmatch
import configparser
from distutils.version import LooseVersion
import typing as t
import logging


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
        logging.info(f"Overriding TZ to {zone_name}")

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
            logging.warning(f"Bad item \"{items[0]}\" found in filesystem overrides")
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


class Migrator:
    def __init__(self, source: str, target: str,
                 ignore: t.Optional[t.Set[str]]=None,
                 rename: t.Optional[t.List[str]]=None,
                 two_steps=False, need_backup=True):
        self.source = source
        assert os.path.isabs(self.source)
        self.target = target
        assert os.path.isabs(self.target)
        self.ignore = ignore or set()
        self.rename = rename or []
        self.no_copy = self.ignore | set(self.rename)
        assert not any(os.path.isabs(i) for i in self.no_copy)
        self.two_steps = two_steps
        self.need_backup = need_backup
        self.target_backup = f'{self.target}.bak'
        self.relocated_source = f'{self.source}.old'
        self.log = logging.getLogger("migration")

    @property
    def need_migration(self):
        return not os.path.islink(self.source)

    def do_migrate(self):
        assert self.need_migration
        # Back-up target if requested
        if self.need_backup and os.path.isdir(self.target):
            self.log.info(f"Copying {self.target} to {self.target_backup}, ignoring {self.no_copy}")
            copytree(self.target, self.target_backup,
                     ignore={os.path.join(self.target, i) for i in self.no_copy})
        # Copy source to target, rename nocopy subdirs
        self.log.info(f"Copying {self.source} to {self.target}, ignoring {self.no_copy}")
        copytree(self.source, self.target,
                 ignore={os.path.join(self.source, i) for i in self.no_copy})
        for rename_path in self.rename:
            if rename_path in self.ignore:
                continue
            _source = os.path.join(self.source, rename_path)
            _target = os.path.join(self.target, rename_path)
            if os.path.isdir(_source):
                self.log.info(f"Renaming {_source} to {_target}")
                os.rename(_source, _target)
        # Remove or move aside source
        if self.two_steps:
            self.log.info(f"Renaming {self.source} to {self.relocated_source}")
            os.makedirs(os.path.dirname(self.relocated_source), exist_ok=True)
            os.rename(self.source, self.relocated_source)
        else:
            self.log.info(f"Deleting {self.source}")
            shutil.rmtree(self.source)
        # Replace source with symlink to target
        target_rel = os.path.relpath(self.target, os.path.dirname(self.source))
        self.log.info(f"Symlinking {self.source} to {target_rel}")
        os.symlink(target_rel, self.source)

    @property
    def need_cleanup(self):
        #TODO check if are not running cleanup right after migration
        return self.two_steps and os.path.isdir(self.relocated_source)

    def do_cleanup(self):
        assert self.need_cleanup
        self.log.info(f"Deleting {self.relocated_source}")
        shutil.rmtree(self.relocated_source)

    def apply(self):
        """
        Return value means whether we need app restart
        """
        if self.need_migration:
            self.do_migrate()
            return self.two_steps
        elif self.need_cleanup:
            self.do_cleanup()
        return False


def _get_host_xdg_mounts(xdg_name: str, flatpak_info):
    assert xdg_name in ["xdg-data", "xdg-config", "xdg-cache"]
    dirs: t.Set[str] = set()
    for filesystem in flatpak_info["filesystems"]:
        filesystem_path = filesystem.rsplit(":", 1)[0]
        path_seq = os.path.normpath(filesystem_path).split(os.path.sep)
        if path_seq[0] == xdg_name:
            dirs.add(os.path.join(*path_seq[1:]))
    return dirs


def migrate_config(flatpak_info):
    """
    There's bind-mounted contents inside config dir so we need to
    1) Relocate, move to temp
    2) Next start of app, remove temp
    In theory this should not break everything
    """
    ignore = _get_host_xdg_mounts("xdg-config", flatpak_info)
    migrator = Migrator(os.path.expandvars("$XDG_CONFIG_HOME"),
                        os.path.join(FLATPAK_STATE_DIR, DEFAULT_CONFIG_DIR),
                        ignore=ignore,
                        two_steps=True)
    should_restart = migrator.apply()
    os.environ["XDG_CONFIG_HOME"] = os.path.expandvars(f"$HOME/{DEFAULT_CONFIG_DIR}")
    return should_restart


def migrate_data(flatpak_info):
    """
    Data directory contains a directory Steam which contains all installed
    games and is massive. It needs to be separately moved
    """
    ignore = _get_host_xdg_mounts("xdg-data", flatpak_info)
    migrator = Migrator(os.path.expandvars("$XDG_DATA_HOME"),
                        os.path.join(FLATPAK_STATE_DIR, DEFAULT_DATA_DIR),
                        two_steps=True,
                        ignore=ignore,
                        rename=["Steam"])
    should_restart = migrator.apply()
    os.environ["XDG_DATA_HOME"] = os.path.expandvars(f"$HOME/{DEFAULT_DATA_DIR}")
    return should_restart


def migrate_cache():
    migrator = Migrator(os.path.expandvars("$XDG_CACHE_HOME"),
                        os.path.join(FLATPAK_STATE_DIR, DEFAULT_CACHE_DIR),
                        need_backup=False)
    should_restart = migrator.apply()
    os.environ["XDG_CACHE_HOME"] = os.path.expandvars(f"$HOME/{DEFAULT_CACHE_DIR}")
    return should_restart


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
    logging.basicConfig(level=logging.DEBUG)
    logging.info("https://github.com/flathub/com.valvesoftware.Steam/wiki")
    current_info = read_flatpak_info(FLATPAK_INFO)
    check_allowed_to_run(current_info)
    should_restart = migrate_config(current_info)
    should_restart += migrate_data(current_info)
    should_restart += migrate_cache()
    if should_restart:
        command = ["/usr/bin/flatpak-spawn"] + sys.argv
        logging.info("Restarting app due to finalize sandbox tuning")
        os.execv(command[0], command)
    else:
        timezone_workaround()
        configure_shared_library_guard()
        enable_discord_rpc()
        os.execv(steam_binary, [steam_binary] + sys.argv[1:])
