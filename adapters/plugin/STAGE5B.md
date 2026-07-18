# Stage 5b – Implementation notes & test plan

## What shipped (v0.7.0)

### PoseBrowser (pose-only AI)
- Removed separate **AI:** search row.
- Normal **Search** bar + **AI** toggle: text filter ∩ Core FTS allowlist when AI is on.
- **Enter** in Search runs local filter + Core search (if AI on).
- Toggle off clears AI allowlist (text-only again).
- **Options → StudioAI → Index all poses**
- Action bar **Index AI** for selected poses
- Selection path APIs on `PoseBrowserExternalApi`

### StudioAi.Plugin
- **F9** Chat window: persona, Send, Analyze scene, Live feedback, Clear
- Live ON → input locked; feedback messages (+ capture thumbnails when `image_path` exists on disk)
- Manual Analyze → feedback bubble, then normal chat
- Pose links `[[pose:path]]` → Show / Apply buttons
- Index jobs via Core `POST /v1/index/paths` (chunked)

### Core
- New `POST /v1/index/paths` — `pose_compact` folders get full offline index; else lightweight filename stub for FTS

---

## Test plan (vollständig)

### A. Deploy
1. Close StudioNEOV2.
2. Copy from `adapters/_deploy_stage/` (or build outputs):
   - `StudioAi.Plugin.dll`, `StudioAi.Contracts.dll` → `BepInEx/plugins/StudioAI/`
   - `HS2Sandbox.PoseBrowser.dll` → usual plugins folder
3. Restart Core (`studio-ai-core` / config.main-pc). Confirm log: `Core LOCKED on http://127.0.0.1:72xx/`.
4. Start Studio; BepInEx log: `StudioAI v0.7.0`.

### B. Unified search (PB)
1. Open PoseBrowser. Confirm **no** second AI search row; only **Search** + **AI** toggle.
2. AI **off**: type a known display name → grid filters locally only; no Core POST in log.
3. AI **on**: type `kneeling`, press **Enter** → BepInEx: `unified search` / `AI search start` / `hits` / `PoseBrowser=filtered`.
4. Status line shows AI hit count; grid = text ∩ AI paths.
5. Toggle AI **off** → allowlist cleared; full text-filtered (or unfiltered) set returns.
6. Clear search text + Enter with AI on → AI filter cleared.

### C. Index (PB → Core)
1. Options → StudioAI → **Index all poses** (start with small library or expect long run).
2. Log: `Index all started` / `POST /v1/index/paths`; status updates; `Index all done`.
3. Select 2–5 poses → **Index AI** on action bar → chunk index for those paths.
4. After index: AI search for a filename token from a selected pose → hits include new stubs / offline entries.
5. Optional: set `Index.UseJoyCaption=true` only if JoyCaption loaded (slow).

### D. Chat (Plugin F9)
1. Press **F9** → Chat window opens; drag works.
2. Send “hello” → assistant reply (Worker/Stheno must be up); error path if Worker offline is clear in bubble.
3. **Analyze scene** (Bridge + JoyCaption required):
   - Success: feedback bubble + thumbnail if PNG written under Core `data/captures/feedback/`.
   - Failure: readable error (bridge/joycaption/paused).
4. After Analyze, send a follow-up chat message → works (input enabled).
5. **Live ON**:
   - Input field disabled; status explains lock.
   - After watch debounce / poll, new feedback bubbles appear (needs Bridge scene + JoyCaption).
6. **Live OFF** → input enabled again.
7. Assistant message containing `[[pose:some/path.png]]` → Show / Apply buttons; Show filters PB; Apply loads pose when path valid.

### E. Separation / degraded
1. Core stopped: Probe fails; Search/Index/Chat show errors; PoseBrowser still usable for normal browse.
2. Confirm Chat is **not** inside PoseBrowser Options (only Index + Probe + status).

### F. Regression
1. Manual PoseBrowser tags still work; AI does not write `PoseTagDatabase`.
2. Probe Core still OK.
3. Contract still `0.4.0`.

### Known limits (honest)
- Agent **tools** (auto search/apply from LLM) are not a full tool-loop yet — pose links are explicit `[[pose:…]]` / buttons.
- **Index (v0.8+):** live path = Plugin applies pose → Core Bridge capture → JoyCaption → merge → SQLite. Needs Studio character loaded, Bridge online, JoyCaption able to load. First caption is slow.
- Live feedback needs working Bridge screenshot + JoyCaption; otherwise Analyze/Live will error clearly.
