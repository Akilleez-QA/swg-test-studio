"""Apply verified fixture overlays without copying unchanged image files."""

LEGACY_BOOT = 'if [ ! -f /opt/whitengold/stage3-overlay-applied ]; then cp -a /overlay/bin/. /opt/whitengold/bin/; cp -a /overlay/lib/. /opt/whitengold/lib/; cp -a /overlay/classes/. /opt/whitengold/data/sku.0/sys.server/compiled/game/; cp -a /overlay/validation/. /opt/whitengold/validation/; touch /opt/whitengold/stage3-overlay-applied; fi; exec "$@"'

# Both trees are validated fixture inputs. Compare bytes and modes before a
# write: overwriting an identical image file still consumes a full writable copy.
SHELL_BOOT = r'''apply_tree() {
    source_root="$1"; target_root="$2"
    mkdir -p "$target_root"
    find "$source_root" -mindepth 1 -type d -exec sh -ec '
        source_root="$1"; target_root="$2"; shift 2
        for source_file do mkdir -p "$target_root/${source_file#"$source_root"/}"; done
    ' sh "$source_root" "$target_root" {} +
    find "$source_root" -type f -exec sh -ec '
        source_root="$1"; target_root="$2"; shift 2
        for source_file do
            target_file="$target_root/${source_file#"$source_root"/}"
            if [ ! -L "$target_file" ] && cmp -s "$source_file" "$target_file" &&
               [ "$(stat -c %a "$source_file")" = "$(stat -c %a "$target_file")" ]; then continue; fi
            cp -a --remove-destination "$source_file" "$target_file"
        done
    ' sh "$source_root" "$target_root" {} +
    find "$source_root" -type l -exec sh -ec '
        source_root="$1"; target_root="$2"; shift 2
        for source_file do
            target_file="$target_root/${source_file#"$source_root"/}"
            if [ -L "$target_file" ] && [ "$(readlink "$source_file")" = "$(readlink "$target_file")" ]; then continue; fi
            cp -a --remove-destination "$source_file" "$target_file"
        done
    ' sh "$source_root" "$target_root" {} +
}
if [ ! -f /opt/whitengold/stage3-overlay-applied ]; then
    apply_tree /overlay/bin /opt/whitengold/bin
    apply_tree /overlay/lib /opt/whitengold/lib
    apply_tree /overlay/classes /opt/whitengold/data/sku.0/sys.server/compiled/game
    apply_tree /overlay/validation /opt/whitengold/validation
    touch /opt/whitengold/stage3-overlay-applied
fi
exec "$@"'''

# Compose interpolates entrypoint strings before /bin/sh sees them.
BOOT = SHELL_BOOT.replace("$", "$$")

# Gameplay classes always come from the verified corpus. Old retained fixtures
# also contain gameplay copies; only their dedicated helper package may overlay it.
GAME_BOOT = BOOT.replace('exec "$$@"',
    'apply_tree /fixture/classes/script/fixture /opt/whitengold/data/sku.0/sys.server/compiled/game/script/fixture\nexec "$$@"')


def refresh_game(entrypoint):
    """Upgrade only recognized game recipes; do not replay stale gameplay copies."""
    if len(entrypoint) < 4 or entrypoint[:2] != ["/bin/sh", "-ec"]:
        raise ValueError("Unexpected fixture game entrypoint")
    old_copy = 'cp -a /fixture/classes/. /opt/whitengold/data/sku.0/sys.server/compiled/game/; exec "$$@"'
    prior = (GAME_BOOT, BOOT, SHELL_BOOT, LEGACY_BOOT,
             BOOT.replace('exec "$$@"', old_copy),
             BOOT.replace('if [ ! -f /opt/whitengold/stage3-overlay-applied ]; then',
                          'if true; then').replace('exec "$$@"', old_copy))
    if entrypoint[2] not in prior:
        raise ValueError("Unrecognized fixture game copy recipe")
    entrypoint[2] = GAME_BOOT


def refresh(entrypoint):
    """Upgrade a known older fixture while preserving role-specific setup."""
    if len(entrypoint) < 4 or entrypoint[:2] != ["/bin/sh", "-ec"]:
        raise ValueError("Unexpected fixture overlay entrypoint")
    script = entrypoint[2]
    if script.endswith(BOOT):
        return
    for prior in (SHELL_BOOT, LEGACY_BOOT):
        if script.endswith(prior):
            entrypoint[2] = script[:-len(prior)] + BOOT
            return
    raise ValueError("Unrecognized fixture overlay copy recipe")
