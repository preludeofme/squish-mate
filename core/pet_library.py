#!/usr/bin/env python3
"""
pet_library.py — the library of selectable pet "species".

Per Ryan's spec: every pet in the library keeps the exact same squishy blob
shape/rig/animations (BlobRenderer + PetAnimator are completely unchanged,
so hop/wave/sleep/giggle/etc. all work identically for every entry) — only
the body color and a light decorative pattern differ. Adding a new species
here means adding a new dict entry, nothing else.
"""

PET_LIBRARY = [
    {
        "id": "pip",
        "name": "Pip",
        "color": "#C9A5F0",
        "pattern": "plain",
        "blurb": "The original lavender blob.",
    },
    {
        "id": "mochi",
        "name": "Mochi",
        "color": "#FFC9DE",
        "pattern": "spots",
        "blurb": "A bubblegum-pink blob with playful spots.",
    },
    {
        "id": "kelp",
        "name": "Kelp",
        "color": "#8FE3B0",
        "pattern": "stripes",
        "blurb": "A minty green blob with tide-pool stripes.",
    },
    {
        "id": "ember",
        "name": "Ember",
        "color": "#FFA36B",
        "pattern": "spots",
        "blurb": "A warm orange blob, freckled like embers.",
    },
    {
        "id": "nocturne",
        "name": "Nocturne",
        "color": "#6B7FE3",
        "pattern": "stars",
        "blurb": "A deep indigo blob dusted with tiny stars.",
    },
    {
        "id": "honeydew",
        "name": "Honeydew",
        "color": "#D9E36B",
        "pattern": "plain",
        "blurb": "A cheerful chartreuse blob, plain and bright.",
    },
    {
        "id": "coral",
        "name": "Coral",
        "color": "#FF7F7F",
        "pattern": "stripes",
        "blurb": "A sunny coral-red blob with reef-like stripes.",
    },
]

DEFAULT_PET_ID = "pip"


def get_pet(pet_id):
    """Look up a species by id; falls back to the default (first) entry so
    a stale/unknown id in a config file never breaks startup."""
    for entry in PET_LIBRARY:
        if entry["id"] == pet_id:
            return entry
    return PET_LIBRARY[0]
