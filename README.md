# Mega Maintenance Depot — Surviving the Aftermath Mod

A "全图维护站" / map-wide Maintenance Depot for **Surviving the Aftermath** (Iceflake Studios, 2021). It auto-repairs every damaged building on the map from a single building.

| Feature | Value |
|---|---|
| Repair range | `workAreaRadius = 500` (map max ≈ 100) |
| Build workers | ≤ 3 (vanilla default) |
| Operating workers | 6 |
| Build cost | 350 Plank + 325 Plastic (5× vanilla Maintenance Depot) |
| Footprint | 10 × 10 (vanilla is 5 × 6) |
| Unlock phase | `minimumGamePhase = 20` (after the colony ceremony, when first residents arrive — matches vanilla Tent) |
| Visual model | Vanilla Maintenance Depot mesh (via cross-bundle PathID swap) |
| Icon | Vanilla Maintenance Depot icon (via spriteatlas external) |
| Localization | 11 languages (12-column CSV matching the game's master localization schema) |

## Requirements

- A copy of **Surviving the Aftermath** (any platform; Linux/Proton tested).
- **Unity Editor 2020.3.14f1** — the exact version Iceflake's modtool targets.
- The official **Iceflake mod toolkit**: <https://github.com/iceflake/survivingtheaftermath>
- **Python 3** with **UnityPy** for the post-build patcher:
  ```sh
  pip install UnityPy
  ```

## Layout

```
.
├── Assets/MegaMaintenance/          ← Unity assets (.asset, .prefab, .png, .loc, .cs)
│   ├── Mod.asset                    Mod manifest (name, version, icon ref, startID)
│   ├── MegaMaintenanceIcon.png      Mod-list icon (134×113, extracted from vanilla spriteatlas)
│   ├── Localization.loc             12-column CSV: id + 11 languages
│   ├── main.script                  IceEngine main script
│   ├── Editor/                      Editor automation script (menu: Mod > Setup And Build…)
│   ├── Prefabs/                     Wrapper prefab for the building visual
│   └── Building/                    Building data + behavior + game event
└── scripts/
    ├── post_build_model_swap.py     Bytes-level patcher (icon, mesh, material, construction)
    └── install.sh                   Pipeline: patch + copy to game + verify
```

## Build

1. **Clone Iceflake's modtool** somewhere:
   ```sh
   git clone https://github.com/iceflake/survivingtheaftermath modtool
   ```

2. **Drop this mod's assets into the toolkit**:
   ```sh
   cp -r Assets/MegaMaintenance modtool/Assets/MegaMaintenance
   ```
   (Or symlink — either works for Unity.)

3. **Open the `modtool` project in Unity 2020.3.14f1**. Wait for the asset import to finish.

4. Menu **`Mod` → `Setup And Build Mega Maintenance`**. This Editor script:
   - Wires up the `WorkAreaChangedEvent` and `MaintenanceBehavior` references on `MegaMaintenanceDepot.asset`.
   - Creates / updates the wrapper prefab (`Prefabs/MaintenanceDepot_Visual.prefab`) — a root with a `BoxCollider(10×3×10)` and a `MaintenanceMesh` child whose `MeshFilter`/`MeshRenderer` start empty (filled in step 5).
   - Calls `LoadBundle.BuildABs()` to produce `modtool/Mods/megamaintenance.mod`.

5. **Run the post-build patcher**:
   ```sh
   MEGA_MAINT_MOD=$PWD/modtool/Mods/megamaintenance.mod \
     python3 scripts/post_build_model_swap.py
   ```
   Or use the one-shot pipeline `install.sh` (it also copies into the game's mod folder + verifies — see below).

## Install

`install.sh` runs the post-build patch, copies the `.mod` into your game's mod folder, and re-reads the installed bytes to verify five things are correct (building icon FileID, construction PathID, Mod-list icon is local, externals include both `ingame` and `spriteatlas`).

```sh
MEGA_MAINT_MOD=$PWD/modtool/Mods/megamaintenance.mod \
STA_MODS_DIR="<path to your game's Mods folder>" \
  bash scripts/install.sh
```

Typical `STA_MODS_DIR` values:

| Platform | Path |
|---|---|
| Linux (Steam + Proton) | `~/.steam/steam/steamapps/compatdata/684450/pfx/drive_c/users/steamuser/Documents/Paradox Interactive/Surviving the Aftermath/Mods` |
| Windows | `%USERPROFILE%\Documents\Paradox Interactive\Surviving the Aftermath\Mods` |
| macOS | `~/Library/Application Support/Paradox Interactive/Surviving the Aftermath/Mods` |

After install: **fully close the game**, restart, enable the mod, then **start a NEW save** — STA locks the mod list to the save's creation time, so old saves won't see the new building.

## How the visual swap works

The vanilla Maintenance Depot mesh, material, sprite, and construction prefab all live in the game's `ingame` and `spriteatlas` bundles. The modtool's Unity project doesn't ship them, so we can't reference them at edit-time. Instead, `post_build_model_swap.py`:

1. Appends `spriteatlas` (`CAB-2d5dc20ed2207adddc6bb95e7e481417`) as **external\[1\]** in the mod's `SerializedFile` headers — `ingame` is already external\[0\] by virtue of `Assets/Configurations` being in the build map.
2. Re-writes specific `MonoBehaviour` / `MeshFilter` / `MeshRenderer` typetree fields in the bundle to point at vanilla PathIDs:
   - `MegaMaintenanceDepot.icon` / `.bigIcon` → `(FileID=2, PathID=8674929843461483915)` (spriteatlas's `BuildingIcon_MaintenanceDepot`)
   - `MegaMaintenanceDepot.models[0].constructions[0]` → `(FileID=1, PathID=-1272999286450079739)` (vanilla construction prefab)
   - Wrapper `MaintenanceMesh.MeshFilter.m_Mesh` → `(FileID=1, PathID=-1905060990077370874)` (vanilla `Building_Maintenance_Depot_LOD0`)
   - Wrapper `MaintenanceMesh.MeshRenderer.m_Materials[0]` → `(FileID=1, PathID=8418554715505181483)` (vanilla shared material)
3. Preserves the modtool's ICEM tail (mod metadata JSON + 5-byte magic) after the bundle.

Important: the **mod-listing icon** (`Mod.icon`, shown in the game's mod selection screen) is **NOT** patched cross-bundle. The mod select UI renders before any in-game bundle is loaded, so a spriteatlas reference would resolve to `null` and crash `ModSelectUI.Setup()` with a NullRef — taking down the entire mod list. Instead, `MegaMaintenanceIcon.png` is shipped as a local asset inside the mod bundle, with importer `isReadable: 1` so the toolkit's `Mod.GenerateMetaData()` can read its pixels via `GetRawTextureData` and bake them into the bundle's metadata.

## Localization

`Localization.loc` is a **12-column CSV** matching STA's master localization schema exactly:

```
id,English,French,German,Spanish,Portuguese,Russian,Polish,Chinese,ChineseTraditional,Japanese,Korean
```

Two gotchas (both will silently fall back to English):

1. **No trailing comma** on header or data rows — the parser will count one extra empty column and shift every subsequent column by one.
2. **Exactly 12 columns** — fewer than 12 makes the whole row fall back to English.

## License

MIT — see `LICENSE` if present, or assume MIT.

This mod ships extracted pixel data of `BuildingIcon_MaintenanceDepot` from the game's spriteatlas as `MegaMaintenanceIcon.png` to work around a Unity importer constraint in the modtool. It is included solely for the mod to function and is not for redistribution outside the mod context.
