using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;
using UnityEngine;

namespace StudioAi.Plugin
{
    /// <summary>
    /// Stage 5b: StudioAI chat + scene feedback (lives in plugin, not PoseBrowser).
    /// F9 toggles visibility. Live feedback locks the input field.
    /// </summary>
    internal sealed class StudioAiChatWindow
    {
        private const int WindowId = 874201;
        private static readonly Regex PoseLinkRegex = new Regex(
            @"\[\[pose:([^\]]+)\]\]",
            RegexOptions.IgnoreCase | RegexOptions.Compiled);

        private readonly StudioAiPlugin _plugin;
        private Rect _rect = new Rect(80, 80, 480, 520);
        private Vector2 _scroll;
        private string _input = "";
        private bool _visible;
        private bool _busy;
        private bool _liveFeedback;
        private bool _chatBusy;
        private string _persona = "stheno";
        private string _status = "";
        private string _lastLiveFingerprint = "";
        private float _livePollAt;
        private readonly List<StudioAiChatMessage> _messages = new List<StudioAiChatMessage>();

        public bool Visible
        {
            get => _visible;
            set
            {
                if (_visible == value) return;
                _visible = value;
                VisibilityChanged?.Invoke(_visible);
            }
        }

        public event Action<bool> VisibilityChanged;

        public bool LiveFeedbackActive => _liveFeedback;

        public StudioAiChatWindow(StudioAiPlugin plugin)
        {
            _plugin = plugin;
            _messages.Add(new StudioAiChatMessage(
                "system",
                "StudioAI Chat. Analyze = one-shot scene feedback (then you can reply). " +
                "Live = periodic feedback; input locked while on. " +
                "Pose links: [[pose:relative/or/absolute/path.png]]"));
        }

        public void Toggle() => Visible = !_visible;

        public void SetVisible(bool visible) => Visible = visible;

        public void OnGUI()
        {
            if (!_visible) return;
            _rect = GUILayout.Window(WindowId, _rect, Draw, "StudioAI Chat (F9)");
        }

        public void Tick()
        {
            if (!_visible || !_liveFeedback) return;
            if (Time.unscaledTime < _livePollAt) return;
            _livePollAt = Time.unscaledTime + 3f;
            _plugin.StartCoroutine(PollLiveLatest());
        }

        private void Draw(int id)
        {
            GUILayout.Label(_status, GUILayout.Height(18));

            GUILayout.BeginHorizontal();
            GUILayout.Label("Persona", GUILayout.Width(52));
            if (GUILayout.Toggle(_persona == "stheno", "Stheno", GUILayout.Width(70)))
                _persona = "stheno";
            if (GUILayout.Toggle(_persona == "satyr", "Satyr", GUILayout.Width(60)))
                _persona = "satyr";
            GUILayout.FlexibleSpace();
            GUILayout.EndHorizontal();

            _scroll = GUILayout.BeginScrollView(_scroll, GUILayout.ExpandHeight(true));
            for (var i = 0; i < _messages.Count; i++)
            {
                var m = _messages[i];
                var label = m.Role + ":";
                GUILayout.Label(label);
                if (m.Thumbnail != null)
                    GUILayout.Box(m.Thumbnail, GUILayout.Width(220), GUILayout.Height(124));
                GUILayout.TextArea(m.Content ?? "", GUILayout.MinHeight(40));

                if (!string.IsNullOrEmpty(m.PoseLink))
                {
                    GUILayout.BeginHorizontal();
                    if (GUILayout.Button("Show in PoseBrowser", GUILayout.Width(150)))
                        StudioAiPlugin.TryShowPoseInBrowser(m.PoseLink);
                    if (GUILayout.Button("Apply pose", GUILayout.Width(100)))
                        StudioAiPlugin.TryApplyPose(m.PoseLink);
                    GUILayout.EndHorizontal();
                }

                // Inline links in content
                foreach (Match match in PoseLinkRegex.Matches(m.Content ?? ""))
                {
                    var path = match.Groups[1].Value.Trim();
                    GUILayout.BeginHorizontal();
                    GUILayout.Label(path, GUILayout.Width(260));
                    if (GUILayout.Button("Show", GUILayout.Width(50)))
                        StudioAiPlugin.TryShowPoseInBrowser(path);
                    if (GUILayout.Button("Apply", GUILayout.Width(50)))
                        StudioAiPlugin.TryApplyPose(path);
                    GUILayout.EndHorizontal();
                }

                GUILayout.Space(6);
            }
            GUILayout.EndScrollView();

            GUILayout.BeginHorizontal();
            GUI.enabled = !_liveFeedback && !_chatBusy;
            _input = GUILayout.TextField(_input ?? "", GUILayout.ExpandWidth(true), GUILayout.Height(24));
            if (GUILayout.Button("Send", GUILayout.Width(56)) && !_liveFeedback && !_chatBusy)
                SendUserMessage();
            GUI.enabled = true;
            GUILayout.EndHorizontal();

            if (_liveFeedback)
                GUILayout.Label("Live feedback ON — typing disabled. Turn Live off to chat.");

            GUILayout.BeginHorizontal();
            GUI.enabled = !_busy && !_chatBusy;
            if (GUILayout.Button("Analyze scene"))
                _plugin.StartCoroutine(RunAnalyze());
            GUI.enabled = !_busy;
            var liveLabel = _liveFeedback ? "Live ON" : "Live OFF";
            if (GUILayout.Button(liveLabel))
                _plugin.StartCoroutine(ToggleLive());
            GUI.enabled = true;
            if (GUILayout.Button("Clear"))
                ClearThread();
            if (GUILayout.Button("Close"))
                Visible = false;
            GUILayout.EndHorizontal();

            GUI.DragWindow();
        }

        private void ClearThread()
        {
            foreach (var m in _messages)
            {
                if (m.Thumbnail != null)
                    UnityEngine.Object.Destroy(m.Thumbnail);
            }
            _messages.Clear();
            _messages.Add(new StudioAiChatMessage("system", "Chat cleared."));
            _lastLiveFingerprint = "";
        }

        private void SendUserMessage()
        {
            var text = (_input ?? "").Trim();
            if (string.IsNullOrEmpty(text)) return;
            _input = "";
            _messages.Add(new StudioAiChatMessage("user", text));
            _plugin.StartCoroutine(RunChat());
        }

        private IEnumerator RunChat()
        {
            _chatBusy = true;
            _status = "Chat…";
            string discoverErr = null;
            yield return StudioAiCoreUnityClient.EnsureResolved(_plugin.CoreUrlHint, e => discoverErr = e);
            if (!string.IsNullOrEmpty(discoverErr))
            {
                AppendAssistant("Core offline: " + discoverErr);
                _chatBusy = false;
                yield break;
            }

            var history = new List<StudioAiChatMessage>();
            foreach (var m in _messages)
            {
                if (m.Role == "system") continue;
                if (m.Role == "feedback") 
                {
                    history.Add(new StudioAiChatMessage("assistant", "[scene feedback]\n" + m.Content));
                    continue;
                }
                history.Add(new StudioAiChatMessage(m.Role, m.Content));
            }

            string reply = null;
            string err = null;
            yield return StudioAiCoreUnityClient.Chat(history, _persona, r => reply = r, e => err = e);
            if (!string.IsNullOrEmpty(err))
                AppendAssistant("Chat error: " + err);
            else
                AppendAssistant(reply ?? "");
            _status = "";
            _chatBusy = false;
        }

        private IEnumerator RunAnalyze()
        {
            _busy = true;
            _status = "Analyzing scene…";
            string discoverErr = null;
            yield return StudioAiCoreUnityClient.EnsureResolved(_plugin.CoreUrlHint, e => discoverErr = e);
            if (!string.IsNullOrEmpty(discoverErr))
            {
                AppendFeedback("Core offline: " + discoverErr, null);
                _busy = false;
                yield break;
            }

            string caption = null;
            string imagePath = null;
            string err = null;
            yield return StudioAiCoreUnityClient.FeedbackAnalyze(
                0, null, true,
                (c, p) => { caption = c; imagePath = p; },
                e => err = e);

            if (!string.IsNullOrEmpty(err))
                AppendFeedback("Analyze failed: " + err, null);
            else
                AppendFeedback(caption ?? "(empty)", imagePath);

            _status = "";
            _busy = false;
        }

        private IEnumerator ToggleLive()
        {
            _busy = true;
            string discoverErr = null;
            yield return StudioAiCoreUnityClient.EnsureResolved(_plugin.CoreUrlHint, e => discoverErr = e);
            if (!string.IsNullOrEmpty(discoverErr))
            {
                _status = discoverErr;
                _busy = false;
                yield break;
            }

            if (!_liveFeedback)
            {
                string err = null;
                yield return StudioAiCoreUnityClient.FeedbackWatchStart(0, 12f, e => err = e);
                if (!string.IsNullOrEmpty(err))
                {
                    AppendFeedback("Live start failed: " + err, null);
                }
                else
                {
                    _liveFeedback = true;
                    _lastLiveFingerprint = "";
                    _livePollAt = 0;
                    AppendFeedback("Live feedback enabled — input locked.", null);
                    StudioAiLog.Info("Live feedback ON");
                }
            }
            else
            {
                string err = null;
                yield return StudioAiCoreUnityClient.FeedbackWatchStop(e => err = e);
                _liveFeedback = false;
                if (!string.IsNullOrEmpty(err))
                    AppendFeedback("Live stop: " + err, null);
                else
                    AppendFeedback("Live feedback disabled — you can type again.", null);
                StudioAiLog.Info("Live feedback OFF");
            }

            _busy = false;
            _status = "";
        }

        private IEnumerator PollLiveLatest()
        {
            string caption = null;
            string imagePath = null;
            string raw = null;
            string err = null;
            yield return StudioAiCoreUnityClient.FeedbackLatest(
                (c, p, r) => { caption = c; imagePath = p; raw = r; },
                e => err = e);
            if (!string.IsNullOrEmpty(err))
                yield break;

            var fp = (imagePath ?? "") + "|" + (caption ?? "");
            if (fp == _lastLiveFingerprint || string.IsNullOrEmpty(caption))
                yield break;
            _lastLiveFingerprint = fp;
            AppendFeedback(caption, imagePath);
        }

        private void AppendAssistant(string text)
        {
            var msg = new StudioAiChatMessage("assistant", text ?? "");
            // First [[pose:...]] becomes primary link buttons
            var m = PoseLinkRegex.Match(text ?? "");
            if (m.Success)
                msg.PoseLink = m.Groups[1].Value.Trim();
            _messages.Add(msg);
            _scroll.y = float.MaxValue;
        }

        private void AppendFeedback(string text, string imagePath)
        {
            var msg = new StudioAiChatMessage("feedback", text ?? "");
            msg.ImagePath = imagePath;
            if (!string.IsNullOrEmpty(imagePath) && File.Exists(imagePath))
            {
                try
                {
                    var bytes = File.ReadAllBytes(imagePath);
                    var tex = new Texture2D(2, 2, TextureFormat.RGBA32, false);
                    if (tex.LoadImage(bytes))
                        msg.Thumbnail = tex;
                    else
                        UnityEngine.Object.Destroy(tex);
                }
                catch (Exception ex)
                {
                    StudioAiLog.Warn("Could not load feedback image: " + ex.Message);
                }
            }
            _messages.Add(msg);
            _scroll.y = float.MaxValue;
        }
    }
}
