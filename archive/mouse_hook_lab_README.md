# Isolated mouse-hook lab

A standalone Windows experiment for observing hook ordering and flags on tagged mouse movement. It is separate from Grove's production child-window input adapter.

## Run

Use an interactive Windows desktop, preferably in a separate VM, with the official client closed:

```powershell
python mouse_hook_lab.py --check
python mouse_hook_lab.py
```

Click the trial button and keep the test window in the foreground. Python's standard library and tkinter are sufficient. A non-interactive shell session cannot validate desktop hook behavior.

## Trial

The lab installs an observing hook followed by a modifying hook. It generates three tagged movement events: baseline, modified, baseline. The modifier clears bits 0 and 1 only for the tagged event in the modified phase. Untagged events are neither logged nor modified. The trial generates no button clicks or keyboard events and removes its hooks when complete or when the window closes.

Results appear in the window and in `mouse_hook_lab_results.json`. Compare observer flags across phases and check the recorded hook order. Missing records, callbacks failing, cleanup errors or failed event submission make the result inconclusive.

## Scope and status

The script refuses to generate events while `osclient.exe` is present and rechecks before each event. This process-name guard is not isolation; use a VM for isolation. `--check` validates native structure layouts and client absence without installing hooks or generating input.

Syntax and native ABI declarations were checked during earlier development. Runtime hook-chain behavior remains unverified. Matching integrity levels may not exercise the lower-integrity flag. The lab does not establish how the official client observes events or whether an input method is detectable.
