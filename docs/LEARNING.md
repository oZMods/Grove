# Learning the framework

Grove is shared as a source of guidance and a baseline for building your own bot or client-interaction framework. The useful starting point is the boundary between reading state, choosing an action and executing it.

## 1. Follow a memory read

Read `grove/clients/osrs.py`. Follow executable validation, module resolution, the selected build profile and the pointer reads that produce raw state. Compare the two profiles to see which offsets moved between reviewed builds.

Run offline recovery using [the recovery guide](OFFSET_RECOVERY.md). Compare the signature matches and decoded references with the saved report. A recovered address is evidence for analysis; it does not prove that a structure's members are unchanged.

## 2. Follow state into the API

Read `grove/api/models.py` and `grove/api/client.py`. Trace a raw inventory or player record into a typed snapshot. Then inspect `grove/api/query.py` to see how filters operate on an existing snapshot without reading the process again.

The [API reference](API.md) includes read-only examples. Attachment requires a reviewed executable hash. Start by understanding snapshots and their limitations before attempting interactions.

## 3. Trace an action

Read `grove/api/contracts.py`, `grove/input/window_messages.py` and the execution paths in `grove/core/runtime.py`. Follow an action expectation through hover, fresh menu checks, input acknowledgment and gameplay acknowledgment.

Notice that a screen coordinate alone is insufficient. The target ID, action, tile and scene instance all contribute to verifying the intended interaction.

## 4. Study navigation and policy

`grove/core/navigation.py` handles collision-aware paths through the loaded map. `grove/core/stepping.py` selects projected waypoints. The woodcutting policy in `grove/bots/woodcutting.py` shows how a policy can use these shared services without duplicating the reader or input adapter.

## 5. Use the tests as examples

From the repository root:

```powershell
python -B -m unittest discover -s tests -p "test_*.py"
```

Build-profile tests show offset selection. API and menu tests show rejected interactions. Navigation tests cover collision behavior. Runtime tests illustrate retries and recovery. These tests use fixtures and mocks; passing them does not establish live compatibility with a new client build.

## Building on the baseline

Keep client-specific layouts separate from policy. Preserve executable validation, treat snapshots as potentially stale, and verify both target identity and action results. Extend one layer at a time and use read-only observations to validate layout changes. See [the validation record](VALIDATION.md) for the current boundaries of the available evidence.
