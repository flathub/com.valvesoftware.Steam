#!/bin/bash
. /etc/os-release

identity() {
    printf "Distributor ID:\t$NAME\n"
}

description() {
    printf "Description:\t$PRETTY_NAME\n"
}

release() {
    printf "Release:\t$VERSION_ID\n"
}

codename() {
    printf "Codename:\tn/a\n"
}

for argument in "$@"
do
    case $argument in
        -h|--help)
            echo This is a shim that reads from /etc/os-release
            ;;
        -i|--id)
            identity
            ;;
        -d|--description)
            description
            ;;
        -r|--release)
            release
            ;;
        -c|--codename)
            codename
            ;;
        -a|--all)
            identity
            description
            release
            codename
            ;;
    esac
done
