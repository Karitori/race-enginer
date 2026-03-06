# Windows Distribution + UX Standards (Desktop Overlay)

Date reviewed: March 6, 2026.

## Packaging standards

1. Build repeatable artifacts
- Use a deterministic build command and version metadata.
- For this repo: `build_overlay_exe.ps1` + `overlay_version_info.txt` + pinned deps in `uv.lock`.

2. Ship both `onedir` and `onefile` builds
- `onedir` is usually easier to debug and maintain.
- `onefile` is convenient for user download.
- PyInstaller officially supports both modes and options like `--windowed`, `--icon`, `--add-data`, `--version-file`.

3. Sign release artifacts
- Microsoft requires signed MSIX packages.
- Microsoft Trusted Signing guidance emphasizes signature + reputation for safer install experience (SmartScreen).
- Do not rely on legacy EV-cert immediate reputation assumptions; Microsoft root policy changed EV handling.

## UI/UX standards for Windows overlays

1. Icon quality
- Follow Windows app icon guidance: clear silhouette, readability across sizes, and asset variants.

2. Settings UX
- Settings should use sane defaults and remain simple/clear.
- Persist user choices and avoid forcing frequent reconfiguration.

3. Accessibility
- Keyboard navigation, focus clarity, and color contrast should be treated as first-class quality gates.
- Include scale/readability controls (font size, opacity, always-on-top toggles).

4. Overlay behavior
- Prefer compact, non-blocking layout with quick actions and minimal visual load.
- Provide fast hide/show behavior and low-latency status signals.
- For game-adjacent overlays, principles from Xbox Game Bar widgets are a useful benchmark.

## Feature baseline expected by users

- Reliable reconnect when backend/game stream drops.
- Quick text input for radio calls.
- Talk-level/verbosity control.
- Persistent settings (position, opacity, host/port, visibility rules).
- Clear connected/listening/error states.
- App/window icon consistency across taskbar/title/exe metadata.

## Sources

- PyInstaller usage/options: https://pyinstaller.org/en/stable/usage.html
- Windows app icon design: https://learn.microsoft.com/en-us/windows/apps/design/style/iconography/app-icon-design
- Windows settings UX guidance: https://learn.microsoft.com/en-us/windows/apps/design/controls/settings
- Xbox Game Bar widget UI guidance: https://learn.microsoft.com/en-us/gaming/game-bar/api/xgb-widget
- MSIX packaging/signing: https://learn.microsoft.com/en-us/windows/msix/packaging-tool/create-app-package
- Microsoft Trusted Signing overview: https://learn.microsoft.com/en-us/azure/trusted-signing/overview
- Microsoft root program requirement update (EV treatment): https://learn.microsoft.com/en-us/security/trusted-root/program-requirements
