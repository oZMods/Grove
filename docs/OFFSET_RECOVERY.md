# Offset recovery

The recovery tool reads an executable on disk and compares it with a reviewed signature manifest. It produces candidate function and global addresses for analysis without attaching to the running client or changing runtime profiles.

## Run

From the repository root:

```powershell
python -m pip install pefile capstone
python tools/recover_offsets.py "C:\Program Files (x86)\Jagex Launcher\Games\Old School RuneScape\Client\osclient.exe" --output recovery/report.json
```

Omit `--output` to print JSON. Use `--manifest archive/client_signatures.json` to select the older baseline. By default, the tool selects `recovery/client_166231c8_signatures.json` when present.

## Evidence produced

Each of the 13 signatures reports its match count and candidate RVAs. For unique matches, the tool decodes the expected RIP-relative instructions, checks their instruction and displacement layouts, and confirms the resolved targets lie in readable PE sections.

References that shared a baseline global are grouped together. Consistent candidates provide evidence that the recovered functions still point to a common location. RTTI analysis identifies type descriptors and structurally matching complete-object locators; these help orient further analysis but do not recover member layouts.

## Latest validation

On October 13, 2026, all 13 signatures matched uniquely and passed encoding checks against executable SHA-256 `a2636a0144b9fed75fefa5de7d1c56a24fe16dcf0222c7e82e9f8bf8f187843f`. All 22 global-reference groups were consistent, and 430 RTTI descriptors were identified.

The baseline for this run was `166231c8f6bd05c7542b8f0d35eb64b0aad701a87ba6ba41f60c4706de946944`. See the [saved report](../recovery/validation_2026-10-13.json).

## Runtime promotion

A successful scan establishes candidate recovery, not complete compatibility. Review changed function semantics and field layouts, validate live state through read-only checks, then add a reviewed build profile. Updating the accepted hash alone is insufficient.

Reports retain `input_authorized=false`. Recovery does not enable input, patch the executable or invoke native client functions.
