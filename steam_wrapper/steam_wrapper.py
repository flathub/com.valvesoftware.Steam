#!/usr/bin/python3
import os
import os.path
import sys
import shutil
import errno
import fnmatch


STEAM_PATH = "/app/bin/steam"


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

def copytree(source, target, ignore=None):
    for root, d_names, f_names in os.walk(source):
        rel_root = os.path.relpath(root, source)
        if ignore:
            d_names[:] = filter_names(root, d_names, ignore)
            f_names = filter_names(root, f_names, ignore)
        if f_names:
            os.makedirs(os.path.join(target, rel_root), exist_ok=True)
        for f_name in f_names:
            full_source = os.path.join(root, f_name)
            full_target = os.path.join(target, rel_root, f_name)
            print (f"Relocating {full_source} to {full_target}")
            shutil.copy2(full_source, full_target)

def check_nonempty(name):
    try:
        with open(name) as file:
            return len(file.read()) > 0
    except IOError as e:
        if e.errno != errno.ENOENT:
            raise
        else:
            return False
        
def legacy_support():
    if not check_nonempty("/etc/ld.so.conf"):
        # Fallback for flatpak < 0.9.99
        os.environ["LD_LIBRARY_PATH"] = "/app/lib:/app/lib/i386-linux-gnu"
        os.environ["STEAM_RUNTIME_PREFER_HOST_LIBRARIES"] = "0"

    steam_home = os.path.expandvars("$HOME/.var/app/com.valvesoftware.Steam/home")
    if os.path.isdir(steam_home):
        # Relocate from old migration
        ignore = ("*/.steam", "*/.local", "*/.var")
        copytree(steam_home, os.path.expandvars("$HOME"), ignore=ignore)
        shutil.rmtree(steam_home)


def main():
    legacy_support()
    #os.execve(STEAM_PATH, [STEAM_PATH] + sys.argv[1:], os.environ)
