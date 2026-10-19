"""Pure domain logic: gesture, wheel session, catalog, geometry, output policy, job types.

No Qt, no ctypes/Win32 and no other Morphwheel layer may be imported here (phase-4 §1, R1;
enforced by import-linter), so every behavioral rule can be unit-tested on any OS.
"""
