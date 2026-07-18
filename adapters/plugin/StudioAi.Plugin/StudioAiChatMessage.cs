namespace StudioAi.Plugin
{
    internal sealed class StudioAiChatMessage
    {
        public string Role;
        public string Content;
        public string ImagePath;
        public string PoseLink;
        public UnityEngine.Texture2D Thumbnail;

        public StudioAiChatMessage(string role, string content)
        {
            Role = role ?? "";
            Content = content ?? "";
        }
    }
}
