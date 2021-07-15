# -*- mode: sh; sh-shell: bash; -*-

# Copyright 2020 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# For further info, check https://github.com/canonical/charmcraft

_charmcraft()
{
    local cur prev words cword cmd cmds
    cmds=(
        build
        clean
        create-lib 
        fetch-lib 
        help init 
        list-lib 
        login 
        logout 
        names 
        pack 
        publish-lib 
        register 
        register-bundle
        release 
        resource-revisions
        resources
        revisions 
        status 
        upload 
        upload-resource
        version 
        whoami
    )
    _init_completion || return

    # only offer long options, as they should be self-explanatory (and
    # it's not like it's more typing for the user)
    globals=(--help --verbose --quiet --project-dir)

    # if user just wrote --project-dir, only offer directories
    if [ "$prev" = "--project-dir" ] || [ "$prev" = "-p" ]; then
        _filedir -d
        return
    fi

    # check if any of the words is a command: if yes, offer the options for that 
    # command (and the global ones), else offer the commands and global options
    local w c
    for w in "${words[@]}"; do
        for c in "${cmds[@]}"; do
            if [ "$c" = "$w" ]; then
                cmd="$c"
                break
            fi
        done
        if [ "$cmd" ]; then
            break
        fi
    done

    if [ -z "$cmd" ]; then
        # no command yet! show global options and the commands
        COMPREPLY=( $(compgen -W  "${globals[*]} ${cmds[*]}" -- "$cur") )
        return
    fi

    # offer the options for the given command (and global ones, always available)
    case "$cmd" in
        build)
            case "$prev" in
                -r|--requirement)
                    _filedir txt
                    ;;
                -e|--entrypoint)
                    _filedir py
                    ;;
                -f|--from)
                    _filedir -d
                    ;;
                *)
                    COMPREPLY=( $(compgen -W "${globals[*]} --from --entrypoint --requirement" -- "$cur") )
                    ;;
            esac
            ;;
        pack)
            case "$prev" in
                -r|--requirement)
                    _filedir txt
                    ;;
                -e|--entrypoint)
                    _filedir py
                    ;;
                *)
                    COMPREPLY=( $(compgen -W "${globals[*]} --entrypoint --requirement --force" -- "$cur") )
                    ;;
            esac
            ;;
        release)
            COMPREPLY=( $(compgen -W "${globals[*]} --revision --channel --resource" -- "$cur") )
            ;;
        init)
            COMPREPLY=( $(compgen -W "${globals[*]} --name --author --force" -- "$cur") )
            ;;
        upload)
            COMPREPLY=( $(compgen -W "${globals[*]} --release" -- "$cur") )
            ;;
        upload-resource)
            case "$prev" in
                --filepath)
                    _filedir
                    ;;
                *)
                    COMPREPLY=( $(compgen -W "${globals[*]} --filepath --image" -- "$cur") )
                    ;;
            esac
            ;;
        *)
            # by default just the global options
            COMPREPLY=( $(compgen -W "${globals[*]}" -- "$cur") )
            ;;
    esac
}
complete -F _charmcraft charmcraft
