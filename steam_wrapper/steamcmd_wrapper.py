#!/usr/bin/python3
import os
import shutil

import steam_wrapper


STEAMCMD_BOOTSTRAP_DIR = "/app/steamcmd"

def main():
    steamcmd_install_dir = os.path.join(
        os.environ.get("XDG_DATA_HOME"), "steamcmd"
    )

    steamcmd_path = os.path.join(
        steamcmd_install_dir, "steamcmd.sh"
    )

    if not os.path.isfile(steamcmd_path):
        if os.path.isfile(os.path.join(STEAMCMD_BOOTSTRAP_DIR, "steamcmd.sh")):
            file_ignorer = steam_wrapper.FileIgnorer(STEAMCMD_BOOTSTRAP_DIR,
                {'metadata', '.ref', 'share'}
            )
            shutil.copytree.copytree(
                STEAMCMD_BOOTSTRAP_DIR,
                steamcmd_install_dir,
                symlinks=True,
                ignore=file_ignorer,
                dirs_exist_ok=True
            )
        else:
            raise OSError("SteamCMD is not installed")

    steam_wrapper.main(steam_binary=steamcmd_path)
