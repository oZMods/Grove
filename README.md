# Grove

An educational framework for studying the official OSRS native client and building your own bot and client-interaction frameworks on 64-bit Windows.

Grove turns native client state into a reusable Python interface: player and scene data, inventories, bank storage, interfaces, collision maps, camera state and menu actions. Its input layer uses the client child window and checks target identity before submitting an action. Build-specific layouts are kept behind executable hash checks, with offline signature recovery to support client updates.

## Why we are sharing this

We are sharing Grove to help people learn how bot and client-manipulation frameworks are built, and to offer a practical baseline for their own projects. If you need guidance on reading game state, organizing build-specific layouts, recovering offsets after updates, or verifying client input, the code and notes provide a baseline to study and build on. We hope sharing the work helps others move their own projects forward and opens the door to useful technical collaboration.

## Learning path

Start with the [learning guide](docs/LEARNING.md). It traces how process memory becomes a snapshot, how queries select targets, and how verified actions reach the client.

The woodcutting policy is a reference implementation for studying the framework. Use it to understand the separation between policy, state access and execution. The current installed client still requires layout review before runtime use; the [validation record](docs/VALIDATION.md) distinguishes offline recovery results from live compatibility.

## Technical scope

- **State access:** read-only process memory, module resolution, native containers and build-specific field offsets.
- **Game model:** player position, skills, inventory, equipment, bank storage, objects, actors, ground items, interfaces and menu state.
- **Spatial data:** native-style screen projection, camera state and collision-aware A* through the loaded map.
- **Interaction:** child-window mouse and keyboard messages, window ownership checks, hover confirmation, exact menu matching and action acknowledgment.
- **Update tooling:** masked function signatures, decoded RIP-relative references, shared-global consistency checks and RTTI evidence.
- **Extension points:** immutable queries, typed snapshots, session ownership, scheduled actions and reusable bot policies.

The production input adapter sends messages to the game window without moving the desktop cursor. The archived hook lab is an independent experiment and is not part of that adapter.

## Start here

Python 3.10 or newer on 64-bit Windows. Offline recovery requires `pefile` and `capstone`.

```powershell
python -m pip install pefile capstone
python tools/recover_offsets.py "C:\Program Files (x86)\Jagex Launcher\Games\Old School RuneScape\Client\osclient.exe" --output recovery/report.json
python -B -m unittest discover -s tests -p "test_*.py"
```

For reviewed client builds, the [Python API](docs/API.md) provides read-only sessions and structured snapshots. Unknown executable hashes are rejected before state access.

## Source layout

- `grove/clients/`: process reader, native layouts and reviewed build profiles.
- `grove/api/`: snapshots, queries, capability checks and verified actions.
- `grove/input/`: Windows structures, geometry, message transport and mouse motion.
- `grove/core/`: sessions, execution, navigation and bounded recovery.
- `grove/bots/`: reference woodcutting policy and runtime registration.
- `tools/` and `recovery/`: offline recovery tooling, signatures and reports.
- `tests/`: state, input, navigation and runtime checks.
- `archive/`: earlier research tools and baseline observations.

This distribution contains the research and runtime sources. The desktop dashboard, overlay and portable launcher are outside its scope.

## Development direction

The reusable state and interaction layers provide a base for additional policies, inspection tools and client-update diagnostics. Near-term work is validating the current build's layouts and live invariants, followed by broader end-to-end coverage. Cross-region transport, doors and stairs, login, world hopping, death recovery and concurrent sessions remain outside the implemented scope.

[API reference](docs/API.md) · [Offset recovery](docs/OFFSET_RECOVERY.md) · [Historical research](archive/README.md)
