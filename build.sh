#!/bin/sh -e
dependencies="--install-deps-from=flathub"
for name in $*
do
    dependencies="--install-deps-from $name $dependencies"
done
flatpak-builder --user $dependencies --repo=steam --force-clean build-dir com.valvesoftware.Steam.yml
flatpak --user remote-add --no-gpg-verify --if-not-exists steam steam
flatpak install steam com.valvesoftware.Steam
flatpak update com.valvesoftware.Steam
