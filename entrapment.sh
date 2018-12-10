_OLD_LD_LIBRARY_PATH=$LD_LIBRARY_PATH
function ld_library_path() {
    if [ -n "$_OLD_LD_LIBRARY_PATH" ]
    then
       if [ "$_OLD_LD_LIBRARY_PATH" != "$LD_LIBRARY_PATH" ]
       then
           LD_LIBRARY_PATH=$_OLD_LD_LIBRARY_PATH:$LD_LIBRARY_PATH
           export LD_LIBRARY_PATH
       fi
    fi
}

declare -t LD_LIBRARY_PATH
trap "ld_library_path" DEBUG
