# StudioAI Bridge adapter (Stage 3)
#
# Core talks to the existing **StudioPoseBridge** BepInEx plugin over HTTP.
# Business logic (posecode, JoyCaption, merge, FTS) stays in Core.

## What Core uses today (no plugin rebuild required)

| Call | Bridge endpoint |
|------|-----------------|
| Health | `GET /v1/health` |
| Characters | `GET /v1/characters` |
| Pose → `pose_compact` | `GET /v1/characters/{id}/pose` (Core formats compact text) |
| Screenshots | `GET /v1/characters/{id}/screenshot?angle=…` |

Views:
- `front` → `angle=front`
- `three_quarter` → `angle=three_quarter`
- `one_quarter` → numeric `angle=45` (config `indexing.cameras.one_quarter_angle`) until a named preset exists

**Capture-only mode:** Apply the pose manually in Studio (or via PoseBrowser), then:

```powershell
studio-ai capture --character 0
# or
studio-ai describe --character 0
```

## Optional future endpoint (not required for Stage 3 acceptance)

```http
POST /v1/indexing/apply-and-capture
X-Pose-Token: …
Content-Type: application/json

{
  "pose_path": "UserData/Studio/pose/….dat",
  "character_id": 0,
  "views": ["front", "three_quarter"],
  "size": 512,
  "framing": "full_body"
}
```

Response should include `pose_compact` + PNG paths/base64. Until this exists, Core falls back to capture-only after manual apply.

Plugin source of truth today: `Repos/AIPoseManager/StudioPoseBridge`  
Config token: `BepInEx/config/com.suitji.studio_pose_bridge.cfg` → set `bridge.token` in `deploy/config.main-pc.yaml`.
