using System;
using System.IO;
using System.Reflection;
using UnityEngine;

namespace StudioAi.Plugin
{
    /// <summary>
    /// Same pattern as HS2-Sandbox <c>ToolbarIconLoader</c>: PNG next to DLL, then embedded resource.
    /// </summary>
    internal static class ToolbarIconLoader
    {
        public static Texture2D LoadPng(string fileName)
        {
            var assembly = Assembly.GetExecutingAssembly();
            var dir = Path.GetDirectoryName(assembly.Location);

            if (!string.IsNullOrEmpty(dir))
            {
                var path = Path.Combine(dir, fileName);
                if (File.Exists(path))
                {
                    try
                    {
                        var tex = CreateTexture(File.ReadAllBytes(path));
                        if (tex.width > 2 || tex.height > 2)
                            return tex;
                    }
                    catch (Exception ex)
                    {
                        StudioAiLog.Warn("Toolbar icon file read failed (" + path + "): " + ex.Message);
                    }
                }
            }

            var embeddedName = assembly.GetName().Name + "." + fileName;
            using (var stream = assembly.GetManifestResourceStream(embeddedName))
            {
                if (stream != null)
                {
                    var ms = new MemoryStream();
                    var buffer = new byte[4096];
                    int read;
                    while ((read = stream.Read(buffer, 0, buffer.Length)) > 0)
                        ms.Write(buffer, 0, read);
                    var tex = CreateTexture(ms.ToArray());
                    if (tex.width > 2 || tex.height > 2)
                        return tex;
                }
            }

            StudioAiLog.Warn("Toolbar icon not found (file next to DLL and embedded): " + fileName);
            return new Texture2D(32, 32);
        }

        private static Texture2D CreateTexture(byte[] data)
        {
            var tex = new Texture2D(2, 2, TextureFormat.ARGB32, false);
            if (data == null || data.Length == 0 || !tex.LoadImage(data))
                StudioAiLog.Warn("Toolbar icon LoadImage failed or empty PNG bytes.");

            tex.wrapMode = TextureWrapMode.Clamp;
            tex.filterMode = FilterMode.Bilinear;
            return tex;
        }
    }
}
