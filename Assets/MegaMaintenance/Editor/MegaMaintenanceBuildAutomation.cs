using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using UnityEditor;
using UnityEngine;
using Debug = UnityEngine.Debug;

public static class MegaMaintenanceBuildAutomation
{
    const string BuildingPath = "Assets/MegaMaintenance/Building/MegaMaintenanceDepot.asset";
    const string PropertyPath = "Assets/MegaMaintenance/Building/MaintenanceBehavior.asset";
    const string EventPath = "Assets/MegaMaintenance/Building/WorkAreaChangedEvent.asset";
    const string WrapperPath = "Assets/MegaMaintenance/Prefabs/MaintenanceDepot_Visual.prefab";

    // Absolute paths used by post-build automation. Hardcoded for this developer machine.
    const string PythonBin       = "/home/mozlet/anaconda3/bin/python3";
    const string PostBuildScript = "/home/mozlet/program/games/surviving-the-aftermath/scripts/post_build_model_swap.py";
    const string BuiltModFile    = "/home/mozlet/program/games/surviving-the-aftermath/modtool/Mods/megamaintenance.mod";
    const string GameModsDir     = "/home/mozlet/G/steamapps/compatdata/684450/pfx/drive_c/users/steamuser/Documents/Paradox Interactive/Surviving the Aftermath/Mods";

    [MenuItem("Mod/Setup And Build Mega Maintenance")]
    public static void SetupAndBuild()
    {
        ScriptableObject ev = EnsureGameEvent();
        ScriptableObject prop = EnsureMaintenanceProperty(ev);
        AttachToBuilding(BuildingPath, prop);
        GameObject wrapper = EnsureWrapperPrefab();
        SetVisualOnBuilding(BuildingPath, wrapper);
        BuildMod();
        if (!RunPostBuildSwap()) return;
        InstallToGameMods();
    }

    static bool RunPostBuildSwap()
    {
        Debug.Log("[MegaMaint] Running post_build_model_swap.py ...");
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = PythonBin,
                Arguments = $"\"{PostBuildScript}\"",
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            using (var proc = Process.Start(psi))
            {
                string stdout = proc.StandardOutput.ReadToEnd();
                string stderr = proc.StandardError.ReadToEnd();
                proc.WaitForExit(120000);
                if (!string.IsNullOrEmpty(stdout))
                    Debug.Log("[post_build stdout]\n" + stdout);
                if (!string.IsNullOrEmpty(stderr))
                    Debug.LogWarning("[post_build stderr]\n" + stderr);
                if (proc.ExitCode != 0)
                {
                    Debug.LogError($"[MegaMaint] post_build_model_swap.py failed with exit code {proc.ExitCode}. " +
                                   $"Run manually: {PythonBin} {PostBuildScript}");
                    return false;
                }
            }
            Debug.Log("[MegaMaint] post_build_model_swap.py succeeded");
            return true;
        }
        catch (Exception e)
        {
            Debug.LogError($"[MegaMaint] Could not invoke {PythonBin}: {e.Message}\n" +
                           $"Run manually: python3 {PostBuildScript}");
            return false;
        }
    }

    static void InstallToGameMods()
    {
        try
        {
            if (!File.Exists(BuiltModFile))
            {
                Debug.LogError($"[MegaMaint] Built mod not found at {BuiltModFile}");
                return;
            }
            if (!Directory.Exists(GameModsDir))
            {
                Debug.LogError($"[MegaMaint] Game Mods dir not found at {GameModsDir}");
                return;
            }
            string dest = Path.Combine(GameModsDir, Path.GetFileName(BuiltModFile));
            File.Copy(BuiltModFile, dest, overwrite: true);
            Debug.Log($"[MegaMaint] Installed to {dest}. Restart game with NEW save.");
        }
        catch (Exception e)
        {
            Debug.LogError($"[MegaMaint] Install failed: {e.Message}\n" +
                           $"Run manually: cp \"{BuiltModFile}\" \"{GameModsDir}/\"");
        }
    }

    // Wrapper prefab: empty MeshFilter/MeshRenderer placeholders.
    // post_build_model_swap.py rewrites these to point at ingame vanilla maintenance depot mesh/material.
    static GameObject EnsureWrapperPrefab()
    {
        string dir = Path.GetDirectoryName(WrapperPath);
        if (!AssetDatabase.IsValidFolder(dir))
        {
            Directory.CreateDirectory(dir);
            AssetDatabase.Refresh();
        }

        GameObject existing = AssetDatabase.LoadAssetAtPath<GameObject>(WrapperPath);
        if (existing != null)
        {
            Debug.Log("[MegaMaint] Wrapper prefab present at " + WrapperPath);
            return existing;
        }

        GameObject root = new GameObject("MaintenanceDepot_Visual");
        BoxCollider bc = root.AddComponent<BoxCollider>();
        bc.size = new Vector3(10f, 3f, 10f);
        bc.center = new Vector3(0f, 1.5f, 0f);

        GameObject meshGo = new GameObject("MaintenanceMesh");
        meshGo.transform.parent = root.transform;
        meshGo.transform.localPosition = Vector3.zero;
        meshGo.transform.localRotation = Quaternion.identity;
        meshGo.transform.localScale = new Vector3(1.8f, 1.8f, 1.8f);
        meshGo.AddComponent<MeshFilter>();
        meshGo.AddComponent<MeshRenderer>();

        GameObject prefab = PrefabUtility.SaveAsPrefabAsset(root, WrapperPath);
        UnityEngine.Object.DestroyImmediate(root);
        AssetDatabase.SaveAssets();
        Debug.Log("[MegaMaint] Created wrapper prefab at " + WrapperPath);
        return prefab;
    }

    static void SetVisualOnBuilding(string buildingPath, GameObject wrapper)
    {
        UnityEngine.Object building = AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(buildingPath);
        if (building == null)
            throw new FileNotFoundException("Building asset not found: " + buildingPath);

        SerializedObject so = new SerializedObject(building);
        SerializedProperty modelsArr = so.FindProperty("models");
        if (modelsArr == null || modelsArr.arraySize == 0)
            throw new InvalidOperationException("models[] empty or missing on " + buildingPath);

        SerializedProperty m0 = modelsArr.GetArrayElementAtIndex(0);
        SerializedProperty visual = m0.FindPropertyRelative("visual");
        SerializedProperty brushVisual = m0.FindPropertyRelative("brushVisual");
        if (visual == null || brushVisual == null)
            throw new InvalidOperationException("visual/brushVisual not found on models[0]");

        visual.objectReferenceValue = wrapper;
        brushVisual.objectReferenceValue = wrapper;
        so.ApplyModifiedPropertiesWithoutUndo();
        AssetDatabase.SaveAssets();
        Debug.Log("[MegaMaint] models[0].visual/brushVisual → wrapper prefab");
    }

    static ScriptableObject EnsureGameEvent()
    {
        Type eventType = FindTypeByName("GameEvent");
        if (eventType == null)
            throw new InvalidOperationException("GameEvent type not found. Need IceEngine.GameEvents.Unity loaded.");

        Debug.Log("[MegaMaint] GameEvent found: " + eventType.FullName + " in " + eventType.Assembly.GetName().Name);

        ScriptableObject ev = AssetDatabase.LoadAssetAtPath<ScriptableObject>(EventPath);
        if (ev == null)
        {
            ev = ScriptableObject.CreateInstance(eventType);
            AssetDatabase.CreateAsset(ev, EventPath);
            AssetDatabase.SaveAssets();
            Debug.Log("[MegaMaint] Created GameEvent asset at " + EventPath);
        }
        return ev;
    }

    static ScriptableObject EnsureMaintenanceProperty(ScriptableObject ev)
    {
        Type maintType = FindTypeByName("MaintenanceProperty");
        if (maintType == null)
            throw new InvalidOperationException("MaintenanceProperty type not found.");

        Debug.Log("[MegaMaint] MaintenanceProperty found: " + maintType.FullName);

        ScriptableObject prop = AssetDatabase.LoadAssetAtPath<ScriptableObject>(PropertyPath);
        if (prop == null)
        {
            prop = ScriptableObject.CreateInstance(maintType);
            AssetDatabase.CreateAsset(prop, PropertyPath);
            Debug.Log("[MegaMaint] Created MaintenanceProperty asset at " + PropertyPath);
        }

        // Wire onWorkAreaChangedEvent to our GameEvent
        SerializedObject so = new SerializedObject(prop);
        SerializedProperty eventProp = so.FindProperty("onWorkAreaChangedEvent");
        if (eventProp == null)
            throw new InvalidOperationException("Field 'onWorkAreaChangedEvent' not found on MaintenanceProperty.");
        eventProp.objectReferenceValue = ev;
        // Also ensure professionType=3 (Maintenance)
        SerializedProperty profProp = so.FindProperty("professionType");
        if (profProp != null)
            profProp.intValue = 3;
        so.ApplyModifiedPropertiesWithoutUndo();
        AssetDatabase.SaveAssets();
        Debug.Log("[MegaMaint] MaintenanceProperty wired: professionType=3, onWorkAreaChangedEvent → GameEvent.");
        return prop;
    }

    static void AttachToBuilding(string buildingPath, ScriptableObject prop)
    {
        UnityEngine.Object building = AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(buildingPath);
        if (building == null)
            throw new FileNotFoundException("Building asset not found: " + buildingPath);

        SerializedObject so = new SerializedObject(building);
        SerializedProperty propArr = so.FindProperty("properties");
        if (propArr == null)
            throw new InvalidOperationException("Field 'properties' not found on " + buildingPath);

        propArr.ClearArray();
        propArr.InsertArrayElementAtIndex(0);
        propArr.GetArrayElementAtIndex(0).objectReferenceValue = prop;
        so.ApplyModifiedPropertiesWithoutUndo();
        AssetDatabase.SaveAssets();
        Debug.Log("[MegaMaint] MaintenanceProperty attached to " + buildingPath);
    }

    public static void BuildMod()
    {
        // Delete any stale .mod from previous build to force a clean write.
        // Without this, BuildPipeline.BuildAssetBundles on Linux can overwrite-without-truncate,
        // leaving prior post-build tail bytes wedged between the new bundle and the new tail.
        // Result: duplicate ICEM tails -> game's AssetBundle loader fails -> Mod metadata
        // shows as #MOD_NAME / #MOD_DESC fallback.
        if (File.Exists(BuiltModFile))
        {
            File.Delete(BuiltModFile);
            Debug.Log("[MegaMaint] Deleted stale " + BuiltModFile + " before fresh build");
        }

        Type loadBundleType = FindTypeByName("LoadBundle");
        if (loadBundleType == null)
            throw new InvalidOperationException("LoadBundle class not found.");

        MethodInfo buildMethod = loadBundleType.GetMethod(
            "BuildABs",
            BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public);
        if (buildMethod == null)
            throw new InvalidOperationException("BuildABs method not found on LoadBundle.");

        Debug.Log("[MegaMaint] Invoking LoadBundle.BuildABs() ...");
        buildMethod.Invoke(null, null);
        Debug.Log("[MegaMaint] Build complete. Output in <project>/Mods/.");
    }

    static Type FindTypeByName(string name)
    {
        foreach (Assembly asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            Type[] types;
            try { types = asm.GetTypes(); }
            catch { continue; }
            foreach (Type t in types)
                if (t.Name == name) return t;
        }
        return null;
    }
}
