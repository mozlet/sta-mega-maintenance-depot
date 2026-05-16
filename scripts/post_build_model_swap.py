#!/usr/bin/env python3
"""
Post-build patcher for megamaintenance.mod.

After Unity Editor (`Mod > Setup And Build Mega Maintenance`) outputs the .mod, this
script edits its bytes to:
  1. Add vanilla `spriteatlas` bundle as external dependency (FileID=2)
  2. Swap building icon/bigIcon -> spriteatlas's BuildingIcon_MaintenanceDepot
  3. Swap models[0].constructions[0] -> ingame vanilla maintenance depot construction prefab
  4. Patch wrapper prefab MeshFilter.m_Mesh   -> ingame Building_Maintenance_Depot_LOD0 mesh
  5. Patch wrapper prefab MeshRenderer.m_Materials -> ingame shared maintenance depot material
  6. Verify Mod.icon is a local (FileID=0) reference — a cross-bundle ref would crash
     the game's mod selection UI (spriteatlas isn't loaded that early).

The wrapper prefab is built in Unity by `MegaMaintenanceBuildAutomation.cs`:
  - root GameObject "MaintenanceDepot_Visual" + BoxCollider (10×3×10)
  - child GameObject "MaintenanceMesh" + empty MeshFilter + empty MeshRenderer (scale 1.8)
post-build fills the empty MeshFilter/MeshRenderer with the ingame mesh/material refs.

Configuration via environment variables:
  MEGA_MAINT_MOD   Path to the freshly built megamaintenance.mod (required).
                   Default: ./modtool/Mods/megamaintenance.mod (relative to repo root)

Requires: pip install UnityPy
"""
import UnityPy
import os
import sys
import shutil
import struct

REPO_ROOT  = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROJECT_MOD = os.environ.get(
    "MEGA_MAINT_MOD",
    os.path.join(REPO_ROOT, "modtool", "Mods", "megamaintenance.mod"),
)
BACKUP_MOD  = "/tmp/megamaintenance_prepatch.mod"

INGAME_CAB = "CAB-7050b12004ed2ff286f49fa4632ca532"
SPRITEATLAS_CAB = "CAB-2d5dc20ed2207adddc6bb95e7e481417"

# Target PathIDs (inside their respective bundles)
INGAME_MAINT_MESH_LOD0    = -1905060990077370874   # Building_Maintenance_Depot_LOD0 mesh
INGAME_MAINT_MATERIAL     = 8418554715505181483    # Shared maintenance depot material
INGAME_MAINT_CONSTRUCTION = -1272999286450079739   # Building_MaintenanceDepot_New_Construction prefab GameObject
SPRITEATLAS_ICON          = 8674929843461483915    # BuildingIcon_MaintenanceDepot Sprite

# Wrapper-internal GameObject name (built by Editor script in Unity)
WRAPPER_MESH_GO_NAME = "MaintenanceMesh"

def ppt(fid, pid): return {"m_FileID": fid, "m_PathID": pid}

def add_spriteatlas_external(cab):
    """Append spriteatlas as a second external in the SerializedFile."""
    for ext in cab.externals:
        if SPRITEATLAS_CAB in ext.name:
            print(f"[deps] spriteatlas already in externals")
            return
    import copy
    template = cab.externals[0]
    new_ext = copy.deepcopy(template)
    new_ext.path = f"archive:/{SPRITEATLAS_CAB}/{SPRITEATLAS_CAB}"
    cab.externals.append(new_ext)
    cab.mark_changed()
    print(f"[deps] added external[{len(cab.externals)-1}]: {new_ext.name}")

def main():
    if not os.path.exists(PROJECT_MOD):
        sys.exit(f"Mod not found at {PROJECT_MOD} (set MEGA_MAINT_MOD env var to override)")
    shutil.copy(PROJECT_MOD, BACKUP_MOD)
    print(f"[backup] {BACKUP_MOD}")

    import io
    with open(PROJECT_MOD, "rb") as f:
        full = f.read()

    # Parse UnityFS header to get bundle's authoritative size.
    # Unity's BuildAssetBundles on Linux overwrites without truncating, so stale post-build
    # tail bytes can sit between the new bundle and the new tail. Read file_size from header.
    if not full.startswith(b"UnityFS\x00"):
        sys.exit(f"Not a UnityFS bundle: {full[:16]!r}")
    off = full.index(b"\x00", 0) + 1            # past signature
    off += 4                                     # version
    off = full.index(b"\x00", off) + 1           # past generator string
    off = full.index(b"\x00", off) + 1           # past engine_version string
    bundle_size = struct.unpack_from(">q", full, off)[0]
    if bundle_size <= 0 or bundle_size > len(full):
        sys.exit(f"Invalid bundle_size in header: {bundle_size} (file size {len(full)})")
    bundle_only = full[:bundle_size]
    after_bundle = full[bundle_size:]

    tail = b""
    if after_bundle.endswith(b"\x01") and len(after_bundle) >= 9 and after_bundle[-5:-1] == b"ICEM":
        json_len = struct.unpack_from("<i", after_bundle, len(after_bundle) - 9)[0]
        tail_size = 5 + 4 + json_len
        if tail_size <= len(after_bundle):
            tail = after_bundle[-tail_size:]
    stale_bytes = len(after_bundle) - len(tail)
    print(f"[bundle] header file_size = {bundle_size} bytes")
    print(f"[tail] preserved metadata: {len(tail)} bytes")
    if stale_bytes > 0:
        print(f"[clean] discarded {stale_bytes} stale bytes between bundle and tail (likely from prior post-build)")

    env = UnityPy.load(io.BytesIO(bundle_only))

    # Sanity: external[0] must be ingame
    cab_file = None
    for cab_name, cab in env.cabs.items():
        if hasattr(cab, "externals") and cab.externals:
            if INGAME_CAB not in cab.externals[0].name:
                sys.exit(f"external[0] != ingame, aborting")
            print(f"[deps] external[0] (FileID=1) = {cab.externals[0].name} (ingame ✓)")
            cab_file = cab
            break

    # Add spriteatlas as external[1] (FileID=2)
    add_spriteatlas_external(cab_file)
    spriteatlas_file_id = next(
        i+1 for i, e in enumerate(cab_file.externals) if SPRITEATLAS_CAB in e.name
    )
    print(f"[deps] spriteatlas FileID = {spriteatlas_file_id}")

    INGAME_FILE_ID = 1
    SA_FILE_ID = spriteatlas_file_id

    # Patch building typetree — building icon, construction.
    # NOTE: Mod.icon (mod-listing icon in game's mod select UI) is handled at the asset layer:
    # Mod.asset references a local PNG (MegaMaintenanceIcon.png, isReadable=1) so Unity bakes
    # actual pixels into the metadata's serializedIcon. We must NOT touch Mod.icon here.
    # Changing it to a cross-bundle (spriteatlas) reference crashes ModSelectUI.Setup() with
    # NullRef because mod selection renders before any in-game bundle loads.
    patched_icon = False
    mod_icon_verified = False
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            tree = obj.read_typetree()
        except Exception:
            continue
        mname = tree.get("m_Name")

        if mname == "MegaMaintenanceDepot":
            print(f"[patch] MegaMaintenanceDepot @ PathID {obj.path_id}")
            tree["icon"]    = ppt(SA_FILE_ID, SPRITEATLAS_ICON)
            tree["bigIcon"] = ppt(SA_FILE_ID, SPRITEATLAS_ICON)
            if tree.get("models") and len(tree["models"]) > 0 and tree["models"][0].get("constructions"):
                tree["models"][0]["constructions"][0] = ppt(INGAME_FILE_ID, INGAME_MAINT_CONSTRUCTION)
                print(f"[patch] models[0].constructions[0] -> ingame maintenance depot construction")
            obj.save_typetree(tree)
            patched_icon = True
        elif mname == "Mod" and "icon" in tree:
            icon = tree["icon"]
            if icon.get("m_FileID") == 0 and icon.get("m_PathID", 0) != 0:
                print(f"[check] Mod listing icon -> local bundle ref (FileID=0, PathID={icon['m_PathID']}) ✓")
                mod_icon_verified = True
            else:
                print(f"[warn] Mod listing icon has unexpected ref: {icon} — expected FileID=0 with non-zero PathID")

    if not patched_icon:
        sys.exit("MegaMaintenanceDepot not found.")
    if not mod_icon_verified:
        print("[warn] Mod listing icon was not verified — check Mod.asset references MegaMaintenanceIcon.png")

    # Find wrapper-internal "MaintenanceMesh" GameObject, then patch its MeshFilter/MeshRenderer
    # to point at ingame vanilla maintenance depot mesh/material.
    mesh_go_pathid = None
    for obj in env.objects:
        if obj.type.name != "GameObject":
            continue
        try:
            tree = obj.read_typetree()
        except Exception:
            continue
        if tree.get("m_Name") == WRAPPER_MESH_GO_NAME:
            mesh_go_pathid = obj.path_id
            print(f"[patch] wrapper MaintenanceMesh GameObject @ PathID {mesh_go_pathid}")
            break

    if mesh_go_pathid is None:
        print("[warn] wrapper 'MaintenanceMesh' GameObject not found in bundle.")
        print("[warn] Skipping mesh/material swap. Visual will be empty (no renderer).")
        print("[warn] Check that MegaMaintenanceBuildAutomation.cs ran and prefab was built into bundle.")
    else:
        mf_patched = mr_patched = False
        for obj in env.objects:
            if obj.type.name not in ("MeshFilter", "MeshRenderer"):
                continue
            try:
                tree = obj.read_typetree()
            except Exception:
                continue
            go_ref = tree.get("m_GameObject", {})
            if go_ref.get("m_PathID") != mesh_go_pathid:
                continue
            if obj.type.name == "MeshFilter":
                tree["m_Mesh"] = ppt(INGAME_FILE_ID, INGAME_MAINT_MESH_LOD0)
                obj.save_typetree(tree)
                print(f"[patch] MeshFilter @ PathID {obj.path_id}: m_Mesh -> ingame LOD0")
                mf_patched = True
            else:
                tree["m_Materials"] = [ppt(INGAME_FILE_ID, INGAME_MAINT_MATERIAL)]
                obj.save_typetree(tree)
                print(f"[patch] MeshRenderer @ PathID {obj.path_id}: m_Materials[0] -> ingame material")
                mr_patched = True
        if not mf_patched:
            print("[warn] MeshFilter for wrapper not patched (component not in bundle?)")
        if not mr_patched:
            print("[warn] MeshRenderer for wrapper not patched (component not in bundle?)")

    bundle_bytes = env.file.save(packer="lz4")
    print(f"[save] new bundle: {len(bundle_bytes):,} bytes")

    with open(PROJECT_MOD, "wb") as f:
        f.write(bundle_bytes)
        if tail:
            f.write(tail)
    print(f"[done] wrote {os.path.getsize(PROJECT_MOD):,} bytes (bundle + ICEM tail)")

    # Verify
    with open("/tmp/verify.mod", "wb") as f:
        f.write(bundle_bytes)
    v = UnityPy.load("/tmp/verify.mod")
    for obj in v.objects:
        if obj.type.name != "MonoBehaviour": continue
        try:
            t = obj.read_typetree()
            if t.get("m_Name") == "MegaMaintenanceDepot":
                print(f"[verify] icon: {t['icon']}")
                print(f"[verify] models[0].visual: {t['models'][0]['visual']}")
                print(f"[verify] models[0].constructions[0]: {t['models'][0]['constructions'][0]}")
            elif t.get("m_Name") == "Mod" and "icon" in t:
                print(f"[verify] Mod listing icon: {t['icon']}")
        except: pass
    for obj in v.objects:
        if obj.type.name not in ("MeshFilter", "MeshRenderer"): continue
        try:
            t = obj.read_typetree()
            go_ref = t.get("m_GameObject", {})
            for go in v.objects:
                if go.path_id == go_ref.get("m_PathID") and go.type.name == "GameObject":
                    name = go.read_typetree().get("m_Name", "")
                    if name == WRAPPER_MESH_GO_NAME:
                        if obj.type.name == "MeshFilter":
                            print(f"[verify] wrapper MeshFilter.m_Mesh: {t['m_Mesh']}")
                        else:
                            print(f"[verify] wrapper MeshRenderer.m_Materials: {t['m_Materials']}")
                    break
        except Exception:
            pass
    for cab_name, cab in v.cabs.items():
        if hasattr(cab, "externals"):
            print(f"[verify] externals in saved bundle:")
            for i, e in enumerate(cab.externals):
                print(f"  [{i}] (FileID={i+1}) {e.name}")
            break
    os.remove("/tmp/verify.mod")
    print("✅ post-build complete")

if __name__ == "__main__":
    main()
