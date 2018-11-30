#!/bin/sh
flatpak-builder --repo=steam --force-clean build-dir com.valvesoftware.Steam.json
flatpak --user remote-add --no-gpg-verify --if-not-exists steam steam
flatpak install steam com.valvesoftware.Steam
flatpak update com.valvesoftware.Steam
