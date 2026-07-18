using System.Collections.Generic;
using System.Threading.Tasks;

namespace StudioAi.Contracts
{
    /// <summary>
    /// Host APIs Pose Browser exposes to StudioAI (implemented in HS2-Sandbox PoseBrowser).
    /// Stage 5b: PB = search filter + index triggers only; Chat/Feedback UI = StudioAi.Plugin.
    /// </summary>
    public interface IPoseBrowserHost
    {
        string? PoseRoot { get; }
        bool TryApplyPoseByPath(string posePath);
        IReadOnlyList<string> EnumerateRelativePosePaths(int limit = 5000);
    }

    public interface IPoseBrowserSearchHost
    {
        bool AiSearchActive { get; }
        void SetAiSearchResults(IEnumerable<string>? paths);
        void ClearAiSearchResults();
    }

    public interface IPoseAiSearchProvider
    {
        Task<SearchResponse?> SearchAsync(string query, int limit = 20);
    }

    public interface IPoseAiIndexProvider
    {
        Task IndexRootAsync(string poseRoot);
        Task IndexPathsAsync(IReadOnlyList<string> absolutePaths);
    }
}
