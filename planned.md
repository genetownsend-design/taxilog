# Planned Enhancements

- [x] Change menu to hamburger menu
- [x] Single-button full backup — downloads a zip of all data files (pickups, customers, profile, expenses, shifts) needed for complete recovery
- [x] Recovery feature — upload a backup zip to restore all data files to a known good state
- [x] Zero out Shift Log fields if the current day's shift has not been saved yet
- [x] Replace all time input fields with an analogue clock picker — 12-hour face, click hour then minute, AM/PM toggle buttons. Use **Clocklet** (MIT, ~7 kB, vanilla JS, no dependencies): https://github.com/luncheon/clocklet — include via CDN, attach to the pickup time, shift start, and shift end fields.
