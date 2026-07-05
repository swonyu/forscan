<!--
  PROVENANCE / VERIFICATION STATUS — READ FIRST
  - Source: "2GFusions - Ford As-Built Data Mods" community spreadsheet by DanMc85
      https://docs.google.com/spreadsheets/d/1yax6zfhZYj2joBczEeruqKh9X5Qhee3C0ngilqwTA7E/pubhtml
      Forum thread: http://www.2gfusions.net/showthread.php?tid=4573
      Retrieved 2026-07-05 (owner-provided).
  - Trust level: COMMUNITY-SOURCED, UNVERIFIED. Every block/line, bit position, and value
      below is a CANDIDATE -> NEEDS ON-CAR CHECK. Block numbers differ by model year and can
      differ across Ford models even for identically-named features.
  - Scope filter: the owner's car is a 2016 Fusion 2.5L "S" (2nd-gen, pre-facelift). Only the
      "2014+ MY" rows apply. The sheet's "2013 MY" rows use DIFFERENT block/line numbers and are
      recorded here only where useful, clearly tagged — do NOT apply them to the 2016.
  - Bit-mask legend (from the sheet): x = ignore this nibble, X = the nibble to change.
      MY = model year. Full-line values include the trailing additive checksum byte.
  - SAFETY: As-Built writes require backup-before-write + read-back verify (see CLAUDE.md /
      ford/asbuilt.py). Central-config / BdyCM writes can reboot the module mid-write — use a
      wired adapter. This file is a REFERENCE, not an executable feature map.
-->

# 2GFusions As-Built Data Mods — 2nd-gen Ford Fusion (2014+ MY, for the 2016 S)

Format per entry: **Feature** — `<module-block-line>` (Module) · mask `<bits>` · options `value = meaning`.
All entries are **UNVERIFIED / NEEDS ON-CAR CHECK**. Confirmed module addresses (per
`ford/fusion_2016.py`): BCM/BdyCM `726`, IPC `720`, APIM `7D0`. Others (DDM `740`, PDM `741`,
ACM `727`, SCCM `724`, FCIM `7A7`, HSWM `714`, FCDIM `7A5`) are plausible but not on the confirmed map.

## Security & alarm

- **Perimeter car alarm** — `726-01-02` (BdyCM) · `xxxx xxxX xxxx` · `1 = enabled`, `0 = disabled`
- **Alarm response** — `726-01-02` (BdyCM) · `xxxX xxxx xxxx` · `0 = light flash + horn (default)`, `1 = light flash only`
- **Panic alarm (key fob)** — `726-37-01` (BdyCM) · `xxxx xxxX xxxx` · `2 = one-press (default)`, `1 = two consecutive presses`, `0 = disabled`
- **SecureIdle** — `726-42-01` (BdyCM) · `xXxx xxxx xxxx` · `0 = disabled (default)`, `1 = enabled` — shifter locked in Park with no passive key detected (adds a factory anti-theft interlock; not a bypass)
- **Dark car mode (police option)** — `726-32-01` (BdyCM) · `xxxx xXxx xxxx` · `0 = disabled (default)`, `1 = enabled`

## Locks, doors, remote

- **Auto relock (if unlocked, not opened within 45 s)** — `726-15-02` (BdyCM) · full-line `xXxX xXxX xXxx` · `0000 0000 0044 = disabled`, `0101 0101 0149 = enabled`, `0202 0202 024E = locked out of IPC`
- **Disable door-lock horn honk (2× fob press)** — `726-38-02` (BdyCM) · `xxxX xxxx xxxx` · `1 = enabled (default)`, `0 = disabled`
- **Door-close double horn honk (engine running, no fob detected / PTS)** — `726-41-02` (BdyCM) · `xxxX xxxx xxxx` · `1 = enabled (default)`, `0 = disabled` — *distinct from the lock-chirp at 726-38-02*
- **Global windows remote CLOSE** — `726-17-01` (BdyCM) · full-line `xXxX xXxX xXxx` · `0101 0101 014A = enabled (default)`, `0000 0000 0045 = disabled`
- **Global windows remote OPEN** — `726-17-02` (BdyCM) · full-line `xXxX xXxX xXxx` · `0101 0101 014B = enabled (default)`, `0000 0000 0046 = disabled`
- **Sunroof comfort vent closure** — `740/741-05-01` (DDM/PDM) · `xxXx xx` · `0 = disabled (default)`, `4 = enabled`
- **Factory remote start (system)** — `726-22-02` (BdyCM) · `xxxX xxxx xxxx` · `0 = disabled`, `1 = enabled`
- **Factory remote start runtime** — `726-20-01` (BdyCM) · `xXxX xXxX xXxx` · `0 = disabled`, `1 = 5 min`, `2 = 10 min`, `3 = 15 min` (set all 5 X's the same; last box = current in-use setting)
- **Remote starter parking lights** — `726-41-02` (BdyCM) · `xxxx xxxX xxxx` · `1 = enabled (default)`, `0 = disabled`
- **Factory remote start dash controls** — `720-02-02` (IPC) · `xxxx XXxx` · `00 = disabled`, `AA = enabled (no heated seats)`, `FA = w/ climate 2013–2014`, `FD = w/ climate 2015+`, `FE = w/ climate + heated wheel`
- **Power point (12V) timeout** — `726-39-01` (BdyCM) · `XXXX xxxx xxxx` · `1194 = 1 h 15 m (default)`, `0001 = off with car`, `5460 = 6 h`, `A8C0 = 12 h`, `FD20 = 18 h`, `FFFF = max`

## Lighting

- **DRL enable — step 1 (unlock all options)** — `726-45-01` (BdyCM) · `xxxx XXxx xxxx` · set the `XX` byte to `7F`
- **DRL enable — step 2 (mode)** — `726-50-01` (BdyCM) · `xXxx` · `01 = disabled / USA default`, `02 = low beams`, `04 = front fog`, `08 = front turn`, `10 = dedicated (BCM outputs C2280C pin 36 R / 40 L)`, `20 = high beams`, `40 = low beams + dedicated`
- **Add DRL control from IPC** — `726-16-02` (BdyCM) · full-line `xXxX xXxX xXxx` · `0202 0202 024F = IPC control locked (2014 default)`, `0101 0101 0049 = enabled (IPC control allowed)`; paired with `726-21-01` (BdyCM) `xxxx xxxx xXxx` `0 = disabled`, `1 = enabled`, `2 = locked out (2014 default)`
- **Front/rear parking lights with DRL** — `726-26-02` (BdyCM) · `xXxx xxxx xxxx` · `0 = disabled (default)`, `1 = enabled`
- **DRL switchback w/ turn signal** — `726-26-02` (BdyCM) · `xxxX xxxx xxxx` · `0 = disabled`, `1 = enabled (default)`
- **Enable OEM fog lights (added after purchase)** — `726-45-02` (BdyCM) `xxxx xXxx xxxx` `1 = present`, `0 = disabled` **+** `720-01-02` (IPC) `xxxx Xxxx` `1 = present`, `0 = disabled` (add 1 to the existing IPC value, don't overwrite)
- **Fog light cornering lights** — `726-26-01` (BCM) · `xxxx xXxx xxxx` · `0 = disabled (default)`, `1 = enabled` (illuminates with turn/steering < 40 km/h)
- **Simultaneous high beams + fogs ("Bambi mode")** — `726-27-01` (BdyCM) · `xxxx xxxX xxxx` · `1 = normal/disabled`, `0 = enabled`
- **Fog light memory** — `726-27-01` (BdyCM) · `xxxx xXxx xxxx` · `0 = remembered on ignition cycle`, `1 = not remembered`
- **High beam memory** — `726-27-01` (BdyCM) · `xxxx xxxx xXxx` · `1 = remembered`, `0 = not remembered`
- **Fog light switchback w/ blinker** — `726-28-02` (BdyCM) · `xxxx xXxx xxxx` · `0 = constant (default)`, `1 = switchback with blinker`
- **Tail light type** — `726-28-01` (BdyCM) · `xxxx xxxx xXxx` · `1 = EU Mondeo`, `3 = S/SE`, `4 = Titanium` (Mondeo may need full line `0101 0101 015B` + `726-28-02 = 0000 0000 0158` for 2016 MY)
- **Rear fog light** — `726-28-01` (BCM) · `xxxx xXxx xxxx` · `0 = disabled (default)`, `1 = enabled` (needs Mondeo tails + wiring)
- **Rear fog light telltale** — `720-02-02` (IPC) · `xxxx xxxX xx` · `2 = enabled`
- **Front turn-signal bulb-out detection** — `726-27-01` (BCM) · `xXxx xxxx xxxx` · `0 = disabled`, `1 = enabled (default)` (set 0 to stop hyperflash with LED bulbs)
- **Automatic turn-signal flash count** — `724-01-01` (SCCM) · `xxxx xXxx xx` · `0 = 1`, `4 = 2`, `6 = 3 (default)`, `8 = 4`, `A = 5`, `C = 6`, `E = 7`

## Instrument cluster (IPC) gauges & chimes

- **AWD gauge** — `720-01-01` (IPC) · `xxxx xXxx xxxx` · `0 = disabled (default)`, `2 = enabled`
- **TPMS gauge** — `720-04-01` (IPC, 2015+) · `xXxx xxxx xxxx` · `0 = disabled`, `4 = enabled`
- **TPMS gauge (factory pressure value shown)** — `720-04-01` (IPC, 2015+) · `xxXx xxxx xxxx` · `0 = disabled`, `8 = enabled`
- **Digital speedometer gauge** — `720-07-01` (IPC, 2015+) · `xxxX xxxx xxxx` · `0 = disabled`, `1 = enabled`
- **30-minute fuel economy history** — `720-02-01` (IPC) · `xXxx xxxx xxxx` · add `4` to the existing value at `X`
- **Dual-screen cluster, right screen** — `720-05-01` (IPC) · `XXXX xxxx xxxx` · `D8B8 = default w/ nav`, `D8A8 = default w/o nav`, plus per-nibble removals (AM/FM/CD, phone, climate menus)
- **Disable IPC welcome screen** — `720-03-02` (IPC) · `xxxX xxxx` · `C = enabled (default)`, `4 = disabled` (remove hex 8: C−8=4)
- **Sound location for chimes** — `720-01-01` (IPC) · `xxxx xxxX xxxx` · `4 = forwarded to ACM/speakers (default)`, `0 = IPC internal speaker only`
- **Door-ajar chime** — `720-01-02` (IPC) · `xxXx xxxx` · `1 = enabled (default)`, `0 = disabled`
- **Key-in-ignition chime** — `720-02-01` (IPC) · `xxXx xxxx xxxx` · subtract `8` from value at `X` to disable
- **Reverse side-mirror tilt** — `720-02-01` (IPC) `xxxx Xxxx xxxx` `3 = disabled (default)`, `7 = enabled` (add 4); mirror modules `740-03-01`/`741-03-01` (DDM/PDM) `6→7`, `740-13-01`/`741-13-01` `00→FC`

## Comfort / convenience

- **Battery type** — `726-04-01` (BdyCM) · `XXxx xxxx xxxx` · `01 = AGM 70Ah 600CCA H6 (default w/ stop-start)`, `02 = AGM 80Ah 700CCA H7`, `12 = Regular 60Ah 600CCA H5 (default SE/Titanium push-start)`, `15 = Regular 90Ah 800CCA H8` (23 total; explore first two bits)
- **Battery monitoring system (BMS)** — `726-04-01` (BdyCM) · `xxxX xxxx xxxx` · `2 = enabled (default)`, `0 = disabled (may lower MPG; recommended off w/ aftermarket stereo)`
- **TPMS (system)** — `726-08-01` (BCM) · `xXxx xxxx xxxx` · `0 = disabled`, `1 = enabled (default)`
- **Heated steering wheel support** — `7A7-01-02` (FCIM) · `xxxX xxxx xxxx` · `0 = disabled`, `8 = enabled` (requires HSW + HSWM module)
- **Heated steering wheel temp** — `714-02-01` (HSWM) · `xxXX XXXX xx` · `44 4444 = 68°F (2013–2015 default)`, `5C 5C5C = 92°F (2016/2017 Fusion default)`, `64 6464 = 100°F (MKZ default)`, and intermediate steps
- **Enable reverse camera** — `7D0-01-01` (APIM, Sync2/3 8″) or `7A5-01-01` (FCDIM, basic 4″) · `xXxx xxxx xxxx` · `0 = disabled`, `2 = enabled`, `A = w/ side-obstacle (2017 Fusion only)`
- **Audio — EQ presets (Sync2 / MyFord Touch only)** — `7D0-01-02` (APIM) · `xxxx xXxx xxxx` · `0 = disabled (default)`, `8 = enabled`
- **Audio — variable line-level preamp** — `727-01-01` (ACM) · `xxXX xxxx xxxx` · `00 = regular (default)`, `A0 = Sony DSP`, `59 = variable line-level w/ sub aux`
- **Audio — remove fake engine noise** — `727-01-01` (ACM) · `xxxx xXxx xxxx` · subtract `2` from the value at `X` to disable

_This reference is a curated transcription of the 2014+ MY rows of the DanMc85 sheet. The sheet also
contains 2013-MY variants (different block/line numbers) and additional detail/notes; consult the source
for anything not captured here. Nothing here is confirmed on the owner's specific VIN._
