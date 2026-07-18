using System.Collections.Generic;
using System.Threading.Tasks;

namespace StudioAi.Contracts
{
    /// <summary>
    /// Host APIs Pose Browser exposes to StudioAI (implemented in HS2-Sandbox PoseBrowser).
    /// Stage 5a — search filter + headless apply. UI host arrives in 5b.
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
}
