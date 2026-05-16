#!/usr/bin/env bash
# Single-shot pipeline: post-build swap + install into game + byte verify.
# Run after Unity Editor builds the mod (menu: Mod > Setup And Build Mega Maintenance).
#
# Configuration via environment variables (override defaults below):
#   PYTHON          Python 3 interpreter with UnityPy installed.
#                   Default: python3
#   MEGA_MAINT_MOD  Path to the freshly built megamaintenance.mod.
#                   Default: ./modtool/Mods/megamaintenance.mod (relative to repo root)
#   STA_MODS_DIR    Game's mod directory (Proton / Wine path on Linux, or
#                   %USERPROFILE%\Documents\... on Windows).
#                   Required if not on the developer's machine.
#
# Example:
#   PYTHON=python3 \
#   MEGA_MAINT_MOD=/path/to/iceflake-modtool/Mods/megamaintenance.mod \
#   STA_MODS_DIR="/home/you/.steam/.../Surviving the Aftermath/Mods" \
#     bash scripts/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
SRC="${MEGA_MAINT_MOD:-modtool/Mods/megamaintenance.mod}"
DST_DIR="${STA_MODS_DIR:-}"

if [[ ! -f "$SRC" ]]; then
  echo "❌ Source mod not found at: $SRC" >&2
  echo "   Set MEGA_MAINT_MOD or run Unity Editor: Mod > Setup And Build Mega Maintenance" >&2
  exit 1
fi

echo "[1/3] post_build_model_swap.py ..."
MEGA_MAINT_MOD="$SRC" "$PY" scripts/post_build_model_swap.py

if [[ -z "$DST_DIR" ]]; then
  echo
  echo "[2/3] STA_MODS_DIR not set — skipping install to game directory."
  echo "       Mod is patched in place at: $SRC"
  echo "       To install: cp \"$SRC\" \"\$STA_MODS_DIR/megamaintenance.mod\""
  exit 0
fi

DST="$DST_DIR/megamaintenance.mod"
echo
echo "[2/3] cp -> $DST"
mkdir -p "$DST_DIR"
cp "$SRC" "$DST"

echo
echo "[3/3] verify installed bundle ..."
INSTALLED_MOD="$DST" "$PY" - <<'PYEOF'
import UnityPy, struct, io, os, sys
PATH = os.environ["INSTALLED_MOD"]
with open(PATH, 'rb') as f:
    d = f.read()
if d[-5:-1] == b'ICEM':
    n = struct.unpack_from('<i', d, len(d) - 9)[0]
    d = d[:-(5 + 4 + n)]
env = UnityPy.load(io.BytesIO(d))
fails = []
for obj in env.objects:
    if obj.type.name != 'MonoBehaviour':
        continue
    t = obj.read_typetree()
    name = t.get('m_Name', '')
    if name == 'MegaMaintenanceDepot':
        if t['icon']['m_FileID'] != 2:
            fails.append(f"building.icon FileID={t['icon']['m_FileID']} (want 2)")
        if t['bigIcon']['m_FileID'] != 2:
            fails.append(f"building.bigIcon FileID={t['bigIcon']['m_FileID']} (want 2)")
        c0 = t['models'][0]['constructions'][0]
        if c0['m_FileID'] != 1:
            fails.append(f"constructions[0] FileID={c0['m_FileID']} (want 1 -> ingame)")
    elif name == 'Mod':
        # Mod.icon MUST stay as local (FileID=0) — cross-bundle ref breaks mod list display.
        if t.get('icon', {}).get('m_FileID') != 0:
            fails.append(f"Mod.icon FileID={t['icon']['m_FileID']} (want 0; cross-bundle breaks mod list)")
ext_count = 0
for _, cab in env.cabs.items():
    if hasattr(cab, 'externals'):
        ext_count = len(cab.externals)
        break
if ext_count < 2:
    fails.append(f"externals count={ext_count} (want >=2, spriteatlas missing)")
if fails:
    print()
    print("❌ FAIL:")
    for x in fails:
        print(f"   - {x}")
    sys.exit(1)
print()
print("✅ READY -- restart game with NEW save")
PYEOF
