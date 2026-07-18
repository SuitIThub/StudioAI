# StudioAI Bridge adapter (Stage 3)
#
# Core talks to the existing **StudioPoseBridge** BepInEx plugin over HTTP.
# Business logic (posecode, JoyCaption, merge, FTS) stays in Core.

## Port discovery

**Why ranges:** After a hard StudioNeoV2 (or process) kill, Windows can leave a ghost LISTEN on the old port until reboot. Binding walks a range so the next start still gets a free port; the peer discovers once and locks.

| Role | Range | Server | Client |
|------|-------|--------|--------|
| StudioPoseBridge | 7100–7199 | Bridge binds first free, keeps it | Core `BridgeClient` discovers once → locks |
| StudioAI Core | 7200–7299 | Core binds first free, keeps it | StudioAi.Plugin discovers once → locks |

Closed ports: cheap TCP skip. First matching `/health` → lock for the process (no re-scan).
`bridge.url` / `Core.BaseUrl` = preferred start only.

## What Core uses today

| Call | Bridge endpoint |
|------|-----------------|
| Health | `GET /v1/health` |
| Characters | `GET /v1/characters` |
| Pose → `pose_compact` | `GET /v1/characters/{id}/pose?regions=…` (+ always `root`) |
| Screenshots (Index) | `GET /v1/characters/{id}/screenshot?angle=front\|three_quarter\|…` |
| Screenshots (Scene Feedback) | `GET /v1/characters/{id}/screenshot?angle=current` (= aktive Studio-Kamera / `Camera.main`) |

### Pose query: regions vs arbitrary bones

**Regions** are named bone groups (`torso`, `hips`, `left_arm`, …). Core requests:

`regions=torso,hips,left_arm,right_arm,left_leg,right_leg`

**Extra FK bones by name** (any bone the rig exposes):

`GET /v1/characters/{id}/pose?bones=cf_J_Neck,cf_J_Hand_L`

Those land in `regions.extra`. Writes already accepted arbitrary bone names; reads now can too.

**Character root / Studio guide** is *not* an FK bone. Bridge always appends a `root` object when available:

```json
"root": {
  "guide_rot_euler": [x, y, z],
  "world_rot_euler": [x, y, z],
  "world_pos": [x, y, z]
}
```

Core flattens that into `pose_compact` as `char_guide:` / `char_root:` so posecode can detect all-fours / prone from whole-character pitch.

**Requires rebuilt StudioPoseBridge** with `AppendRootTransforms` + `bones=` query support. Rebuild the plugin DLL and reload Studio / BepInEx.

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
