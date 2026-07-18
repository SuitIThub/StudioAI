using System;
using BepInEx.Logging;

namespace StudioAi.Plugin
{
    /// <summary>Thin wrapper so Unity client + plugin share one BepInEx log source.</summary>
    internal static class StudioAiLog
    {
        public static bool Verbose { get; set; } = true;

        private static ManualLogSource _source;

        public static void Bind(ManualLogSource source) => _source = source;

        public static void Info(string msg) => _source?.LogInfo(msg);

        public static void Debug(string msg)
        {
            if (!Verbose) return;
            // Default BepInEx often hides Debug; use Info when Verbose so it lands in LogOutput.log
            _source?.LogInfo("[dbg] " + msg);
        }

        public static void Warn(string msg) => _source?.LogWarning(msg);

        public static void Error(string msg) => _source?.LogError(msg);

        public static void Error(string msg, Exception ex)
        {
            _source?.LogError(msg + ": " + ex.GetType().Name + " — " + ex.Message);
            if (Verbose && ex.StackTrace != null)
                _source?.LogError(ex.StackTrace);
        }
    }
}
