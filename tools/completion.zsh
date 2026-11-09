# A `tado` command with tab completion, usable from any directory.
#
# Add this to ~/.zshrc, after compinit:
#
#   source /path/to/tado-data/tools/completion.zsh
#
# Completion is bound to `tado` rather than to `uv run python tado.py` because
# zsh dispatches completion on the first word. That word would be `uv`, which
# football-stats already binds, and zsh allows only one completion per command.
#
# The choices come from Click, so new commands appear without changing this
# file. Completing only parses the command line; it never calls the Tado API.

_TADO_DIR=${${(%):-%x}:A:h:h}

tado() {
    uv run --directory "$_TADO_DIR" python tado.py "$@"
}

_tado_completion() {
    local -a response described plain
    local type key descr

    # Click names the variable after the program it sees, which here is tado.py.
    response=("${(@f)$(env COMP_WORDS="${(j: :)words}" COMP_CWORD=$((CURRENT - 1)) \
        _TADO_PY_COMPLETE=zsh_complete \
        uv run --directory "$_TADO_DIR" python tado.py 2>/dev/null)}")

    for type key descr in ${response}; do
        if [[ "$type" == "plain" ]]; then
            if [[ "$descr" == "_" ]]; then
                plain+=("$key")
            else
                described+=("$key":"$descr")
            fi
        fi
    done

    (( ${#described} )) && _describe -V unsorted described -U
    (( ${#plain} )) && compadd -U -V unsorted -a plain
}

compdef _tado_completion tado
