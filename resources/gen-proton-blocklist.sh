#!/usr/bin/env bash

declare -A PROTON_BLOCK_LIBS

PROTON_BLOCK_LIBS["Proton 3.7"]="libFAudio.so"
PROTON_BLOCK_LIBS["Proton 3.7 Beta"]="libFAudio.so"
PROTON_BLOCK_LIBS["Proton 3.16"]="libFAudio.so"
PROTON_BLOCK_LIBS["Proton 3.16 Beta"]="libFAudio.so"
PROTON_BLOCK_LIBS["Proton 4.2"]="libFAudio.so.0.19.06"
PROTON_BLOCK_LIBS["Proton 4.11"]="libFAudio.so.19.08 libFAudio.so.19.09"

for proton in "${!PROTON_BLOCK_LIBS[@]}"; do
    dist_dir=$(printf '%q' "${proton}/dist")
    for block_lib in ${PROTON_BLOCK_LIBS[$proton]}; do
        for arch_suffix in "64" ""; do
            for wine_bin in "wine${arch_suffix}" "wine${arch_suffix}-preloader"; do
                echo "${dist_dir}/bin/${wine_bin} ${dist_dir}/lib${arch_suffix}/${block_lib}"
            done
        done
    done
done
