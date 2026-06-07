# Focus Forge (PySide6)

Native Windows visual focus tree editor for Hearts of Iron IV / Millennium Dawn. Authors `.focusforge.json` projects, exports HOI4 `.txt` focus trees, localization `.yml`, ideas, and events.

This is the PySide6 rewrite of the Electron/React prototype (sibling folder `hoi4-focus-forge`). Output is byte-identical to the original.

## Run

```powershell
python -m pip install PySide6
python main.py
```

## Tests

```powershell
python -m pip install pytest
python -m pytest tests/ -v
```

## Build the .exe

```powershell
python -m pip install pyinstaller
pyinstaller build.spec --clean --noconfirm
```

Produces `dist/FocusForge.exe` (~45 MB single-file).

## Layout

- `core/` — pure-Python data model, validation, exporters, reward presets, base tree, country tags
- `ui/` — QMainWindow + ProjectModel + graph view + inspector + reward editor + tabs
- `tests/` — pytest suite mirroring the original TS tests

## Parity with the Electron app

Exporter output is byte-for-byte identical (no CRLF; UTF-8 with BOM where the spec calls for it). Drop a `.focusforge.json` from either app into the other and round-trip exports match.
