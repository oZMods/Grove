# Official client state reader and signature baseline

These files are the original research tools for `osclient.exe` SHA-256 `3852dd48aa6a75cfb042489b5192b477a1b828cbc95af8b759c139095c8b6ea2`. They're how the offsets in `grove/clients/osrs.py` were found. The maintained reader and runtime are in `../grove/`. Use these historical tools to trace an offset or compare a new build with the original baseline.

## Read a snapshot (PowerShell)

```powershell
pwsh -NoProfile -File .\read_client_state.ps1
# Multiple clients running:
pwsh -NoProfile -File .\read_client_state.ps1 -ClientProcessId 15440
```

Opens the process for read/query access only, verifies the executable hash, finds the module base each run, and dumps a snapshot. Snapshots aren't atomic. If the player is moving or a bank is opening mid-read, some fields will be from slightly different moments. Just run it again once things settle.

Validated live against the client:

- Woodcutting level and XP (effective, base, raw XP value)
- Inventory item IDs and quantities for containers 93 (inventory), 94 (equipment), 95 (bank storage)
- Local player tile position (x, y, plane)
- Nearby scene objects with definition IDs, tile coordinates, and projected screen points
- Animation and route state on the local player
- Tree and bank booth definitions with Chop down/Bank menu entries matched against scene object IDs
- Bank open/closed state via the interface manager
- Menu actions including selective Deposit-All for specific item slots

Bank inventory is group 15, component 3. Child sub-IDs map to inventory slots. Item IDs in the widget have to be cross-checked against container 93 because the bank UI can hold placeholder entries that don't match what's actually stored.

Observed bank close component at group/sub-ID `(786434, 11)`, screen candidate `(779, 19)`. Live menu confirmed same identity. Bank slot hover at native pointer `(1194, 425)` matched calculated slot 1 bounds `(1179, 409, 36, 32)`.

Tree screen points are approximate because they use native projection with a simplified height value. A Chop down hover on Tree 1276 at `(3168, 3413)` projected to `(575, 273)` against a native pointer of `(576, 270)` and confirmed the matching menu entry. Close enough for targeting purposes.

`DefaultMenuCandidate` follows the native first-leaf selection through the ordered menu tree (manager+640/+648, 24-byte entries) rather than assuming raw vector order. That's what the Walk-here and Chop-down observations used. Flags 327/328 and `ClientMenuSetting` are exported because the native input path can open a context menu instead of activating the default. Both states need to be handled.

## Scan signatures (Python)

Requires `pefile` and `capstone`.

```powershell
python .\client_signatures.py scan 'C:\Program Files (x86)\Jagex Launcher\Games\Old School RuneScape\Client\osclient.exe'
```

Thirteen signatures, all uniquely matching the baseline build. Covers: stat access (effective/base/XP), inventory item and quantity lookup, loc type loading and menu construction, native projection, interface group retrieval, action animation, and default-action activation. RIP-relative displacements, relative branches/calls, and PE relocations are all masked in the patterns.

The scanner exports candidate RVAs and decoded RIP references for each match. A new executable hash comes back as `needs_analysis` even when a pattern matches uniquely. This status requires further layout review. A matching byte sequence doesn't validate that the surrounding struct layout hasn't changed. Always review the function in IDA and validate offsets manually before updating the reader.

Named signatures with baseline RVAs:

| Signature | RVA |
|---|---|
| `ClientState_getStatEffectiveLevel` | 0xF5890 |
| `ClientState_getStatXP` | 0xF58C0 |
| `ClientState_getStatBaseLevel` | 0xF58F0 |
| `Inventory_GetItemId` | 0x30D70 |
| `Inventory_GetQuantity` | 0x30DD0 |
| `Player_SetActionAnimation` | 0x714B0 |
| `LocType_GetOrLoadById` | 0x5ED140 |
| `SceneTile_FindLocType` | 0x6A2D90 |
| `Lua_RegisterLocTypeBindings` | 0xF4940 |
| `Menu_BuildLocEntries` | 0x383790 |
| `Scene_ProjectWorldPoint` | 0x6AA8A0 |
| `LuaIfType_retrieveIfGroup` | 0x228370 |
| `MenuInput_ActivateOrderedFirstAction` | 0x380B00 |

Keep this baseline when researching a new build. Even a single offset shift will produce wrong reads without errors, which is worse than a crash.

## Hook tracing notes

`InputHookDiagnostics` in `read_client_state.ps1` traces the live hook callback chain read-only. Hook callbacks pass through `thunk6D16D0`, then `6D0900`/`6D0890` to queue methods `6CF270`/`6CF230`. Event records are 32 bytes: type+0, message+4, hook flags+8, X+12, Y+16, time+24. Types 11/10 are movement/button. Queue drain at `6CEEA0` dispatches through `6CC6F0` to registered listeners. Movement samples coalesce in 50ms buckets (max 500). No flag rejection was found along this path. The trace used read-only access. No queue writes were performed.

## Validation boundaries

automated click, walk, chop, and bank deposit was tested by these tools. 

`HoveredSceneTargets` joins menu entries to scene objects by definition ID and world coordinates. A second bank hover changed the observed metadata from Logs at slot 1 to Mithril axe at slot 0, and pointer `(1151, 423)` matched the axe slot 0 bounds. These are one-capture observations at one client scale not a guarantee for all zoom levels or interface layouts.
