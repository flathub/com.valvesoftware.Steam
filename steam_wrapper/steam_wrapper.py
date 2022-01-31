#!/usr/bin/python3
import os
import os.path
from pathlib import Path
import sys
import shutil
import errno
import fnmatch
import configparser
from distutils.version import LooseVersion
import typing as t
import logging
import subprocess

import posix1e


FLATPAK_ID = os.getenv("FLATPAK_ID", "com.valvesoftware.Steam")
STEAM_PATH = "/app/bin/steam"
FLATPAK_STATE_DIR = os.path.expanduser(f"~/.var/app/{FLATPAK_ID}")
XDG_DATA_HOME = os.environ["XDG_DATA_HOME"]
XDG_CACHE_HOME = os.environ["XDG_CACHE_HOME"]
XDG_RUNTIME_DIR = os.environ["XDG_RUNTIME_DIR"]
DEFAULT_CONFIG_DIR = ".config"
DEFAULT_DATA_DIR = ".local/share"
DEFAULT_CACHE_DIR = ".cache"
FLATPAK_INFO = "/.flatpak-info"
# List of symlinks under ~/.steam relative to xdg-data
STEAM_SYMLINKS = {
    "bin32": "ubuntu12_32",
    "bin64": "ubuntu12_64",
    "root": ".",
    "sdk32": "linux32",
    "sdk64": "linux64",
    "steam": ".",
}
ALLOWED_XDG_DIRS_PREFIXES = [
    os.path.expanduser("~"),
    FLATPAK_STATE_DIR,
]
EXTENSIONS = {
    "org.freedesktop.Platform.VulkanLayer": {
        "mountpoint": "/usr/lib/extensions/vulkan",
        "append-env": {
            "PATH": [ "bin" ],
        },
    },
}
WIKI_URL = f"https://github.com/flathub/{FLATPAK_ID}/wiki"


class Message(t.NamedTuple):
    msg_id: str
    title: str
    text: str
    always_show: bool

    def show(self) -> bool:
        logging.warning(self.title)
        stamp = Path(XDG_DATA_HOME) / "steam-wrapper" / "messages" / self.msg_id
        if not self.always_show and stamp.exists():
            return False
        subprocess.run(
            ["zenity", "--no-wrap", "--warning", "--title", self.title, "--text", self.text],
            check=True, text=True,
        )
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.touch()
        return True


MSG_NO_INPUT_DEV_PERMS = Message(
    "no-input-dev-perms",
    "Missing permissions for input devices",
    (
        "Steam input devices UDEV rules don't seem to be installed, "
        "gamepads may not work properly.\n"
        "Consider installing \"steam-devices\" package using your distro package manager.\n"
        "See the Steam flatpak "
        f"<a href=\"{WIKI_URL}#my-controller-isnt-being-detected\">wiki</a> "
        "for more details."
    ),
    False,
)


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
        "runtime-extensions": dict((s.split("=")
                                   for s in flatpak_info.get("Instance", "runtime-extensions",
                                                             fallback="").split(";") if s)),
        "filesystems": flatpak_info.get("Context", "filesystems",
                                        fallback="").split(";")
    }


def env_is_true(env_str: str):
    if env_str.lower() in ["y", "yes", "true"]:
        return True
    if env_str.lower() in ["n", "no", "false"]:
        return False
    if env_str.isdigit():
        return bool(int(env_str))
    return None


def read_file(path):
    try:
        with open(path, "r") as f:
            return f.read()
    except IOError as e:
        if e.errno == errno.ENOENT:
            return ""
        raise


def check_device_perms():
    has_perms = False
    logging.debug("Checking input devices permissions")
    uinput_path = Path("/dev/uinput")
    if uinput_path.exists():
        for entry in posix1e.ACL(file=uinput_path):
            if (entry.tag_type == posix1e.ACL_USER
                and entry.qualifier == os.geteuid()
                and entry.permset.write):
                has_perms = True
                break
    if not has_perms:
        MSG_NO_INPUT_DEV_PERMS.show()
    return has_perms


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
        faq = f"{WIKI_URL}#i-want-to-add-external-disk-for-steam-libraries"
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
                 two_steps=True, need_backup=True):
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


def migrate_config(flatpak_info, xdg_dirs_prefix):
    """
    There's bind-mounted contents inside config dir so we need to
    1) Relocate, move to temp
    2) Next start of app, remove temp
    In theory this should not break everything
    """
    ignore = _get_host_xdg_mounts("xdg-config", flatpak_info)
    migrator = Migrator(os.path.expandvars("$XDG_CONFIG_HOME"),
                        os.path.join(FLATPAK_STATE_DIR, DEFAULT_CONFIG_DIR),
                        ignore=ignore)
    should_restart = migrator.apply()
    if xdg_dirs_prefix:
        os.environ["XDG_CONFIG_HOME"] = os.path.join(
            os.path.expanduser(xdg_dirs_prefix),
            DEFAULT_CONFIG_DIR,
        )
    return should_restart


def migrate_data(flatpak_info, xdg_dirs_prefix):
    """
    Data directory contains a directory Steam which contains all installed
    games and is massive. It needs to be separately moved
    """
    ignore = _get_host_xdg_mounts("xdg-data", flatpak_info)
    migrator = Migrator(os.path.expandvars("$XDG_DATA_HOME"),
                        os.path.join(FLATPAK_STATE_DIR, DEFAULT_DATA_DIR),
                        ignore=ignore,
                        rename=["Steam"])
    should_restart = migrator.apply()
    if xdg_dirs_prefix:
        os.environ["XDG_DATA_HOME"] = os.path.join(
            os.path.expanduser(xdg_dirs_prefix),
            DEFAULT_DATA_DIR,
        )
    return should_restart


def migrate_cache(flatpak_info, xdg_dirs_prefix):
    ignore = _get_host_xdg_mounts("xdg-cache", flatpak_info)
    migrator = Migrator(os.path.expandvars("$XDG_CACHE_HOME"),
                        os.path.join(FLATPAK_STATE_DIR, DEFAULT_CACHE_DIR),
                        ignore=ignore,
                        need_backup=False)
    should_restart = migrator.apply()
    if xdg_dirs_prefix:
        os.environ["XDG_CACHE_HOME"] = os.path.join(
            os.path.expanduser(xdg_dirs_prefix),
            DEFAULT_CACHE_DIR,
        )
    return should_restart


def get_current_xdg_dir_prefix():
    steam_root_link = os.path.expanduser("~/.steam/root")
    if not (os.path.isdir(steam_root_link) and os.path.islink(steam_root_link)):
        logging.error("~/.steam/root isn't a symlink to an existing directory, "
                      "cannot determine current prefix")
        return None
    current_steam_root = os.readlink(steam_root_link)
    # FIXME we need a more reliable way to determine current prefix
    # here we assume that ~/.steam/root points to ~/.local/share/Steam
    # this will break if `steam` was first ran bypassing the wrapper
    current_prefix = os.path.normpath(os.path.join(current_steam_root, "..", "..", ".."))
    return current_prefix


def shift_steam_symlinks(current_prefix, new_prefix):
    if not current_prefix or not new_prefix:
        return False
    new_prefix = os.path.normpath(new_prefix)
    assert new_prefix in ALLOWED_XDG_DIRS_PREFIXES, new_prefix
    current_prefix = os.path.normpath(current_prefix)
    assert current_prefix in ALLOWED_XDG_DIRS_PREFIXES, current_prefix
    if new_prefix == current_prefix:
        return False
    logging.info(f"Changing XDG dirs prefix from {current_prefix} to {new_prefix}")
    shifted = False
    for name in STEAM_SYMLINKS:
        symlink = os.path.expanduser(f"~/.steam/{name}")
        assert os.path.islink(symlink)
        current_target = os.readlink(symlink)
        new_target = os.path.join(
            new_prefix,
            os.path.relpath(current_target, current_prefix)
        )
        if not os.path.isdir(new_target):
            logging.error(f"Symlink {symlink}: new target {new_target} does not exist, skipping")
            continue
        logging.warning(f"Symlink {symlink}: replacing with new target {new_target}")
        os.remove(symlink)
        os.symlink(new_target, symlink)
        shifted = True
    return shifted


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


def enable_extensions(flatpak_info):
    installed_ext_ids: t.Set[str]
    installed_ext_ids = set(flatpak_info["app-extensions"])
    installed_ext_ids |= set(flatpak_info["runtime-extensions"])
    for ext_id, ext in EXTENSIONS.items():
        for installed_ext_id in installed_ext_ids:
            if not installed_ext_id.startswith(f"{ext_id}."):
                continue
            ext_basename = installed_ext_id[len(f"{ext_id}."):]
            for env_var, subdirs in ext["append-env"].items():
                paths = [p for p in os.environ.get(env_var, "").split(os.pathsep) if p]
                for subdir in subdirs:
                    dir_path = os.path.join(ext["mountpoint"], ext_basename, subdir)
                    logging.debug(f"Addding {dir_path} to {env_var}")
                    paths.append(dir_path)
                os.environ[env_var] = os.pathsep.join(paths)


def configure_shared_library_guard():
    mode = int(os.environ.get("SHARED_LIBRARY_GUARD", 1))
    if not mode:
        return
    else:
        os.environ["LD_AUDIT"] = f"/app/links/$LIB/libshared-library-guard.so"


def main(steam_binary=STEAM_PATH):
    os.chdir(os.environ["HOME"]) # Ensure sane cwd
    logging.basicConfig(level=logging.DEBUG)
    logging.info(WIKI_URL)
    current_info = read_flatpak_info(FLATPAK_INFO)
    check_allowed_to_run(current_info)
    should_update_symlinks = env_is_true(os.environ.get("FLATPAK_STEAM_UPDATE_SYMLINKS", "0"))
    current_xdg_prefix = get_current_xdg_dir_prefix()
    if not current_xdg_prefix or should_update_symlinks:
        xdg_dirs_prefix = os.environ.get("FLATPAK_STEAM_XDG_DIRS_PREFIX")
        assert not xdg_dirs_prefix or xdg_dirs_prefix.startswith("~")
        xdg_dirs_prefix = os.path.expanduser(xdg_dirs_prefix)
    else:
        xdg_dirs_prefix = current_xdg_prefix
    logging.info(f"Will set XDG dirs prefix to {xdg_dirs_prefix}")
    should_restart = migrate_config(current_info, xdg_dirs_prefix)
    should_restart += migrate_data(current_info, xdg_dirs_prefix)
    should_restart += migrate_cache(current_info, xdg_dirs_prefix)
    if should_restart:
        command = ["/usr/bin/flatpak-spawn"] + sys.argv
        logging.info("Restarting app due to finalize sandbox tuning")
        os.execv(command[0], command)
    else:
        if should_update_symlinks:
            shift_steam_symlinks(current_xdg_prefix, xdg_dirs_prefix)
        check_device_perms()
        timezone_workaround()
        configure_shared_library_guard()
        enable_extensions(current_info)
        enable_discord_rpc()
        os.execv(steam_binary, [steam_binary] + sys.argv[1:])
