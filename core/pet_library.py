#!/usr/bin/env python3
"""
pet_library.py — the library of selectable pet "species".

Per Ryan's spec: every pet in the library keeps the exact same squishy
rig/animation pipeline (BlobRenderer + PetAnimator are unchanged — hop/
wave/sleep/giggle/etc. all work identically for every entry, driven by the
same Pose fields). What actually varies per species now:
  - "shape"   — body silhouette archetype (see ui/blob_renderer.SHAPE_PRESETS:
                proportions, top taper, arm reach, antenna style, horns).
                This is the main visual differentiator Ryan asked for.
  - "color"   — base body hex (also independently editable via the existing
                Settings color picker, so this is just each species' default).
  - "pattern" — light decorative overlay (spots/stripes/stars/plain).
Adding a new species here means adding a new dict entry, nothing else.
"""

PET_LIBRARY = [
    {
        "id": "pip",
        "name": "Pip",
        "color": "#C9A5F0",
        "shape": "round",
        "pattern": "plain",
        "blurb": "The original round lavender blob.",
    },
    {
        "id": "mochi",
        "name": "Mochi",
        "color": "#FFC9DE",
        "shape": "wide",
        "pattern": "spots",
        "blurb": "A squashed, bubblegum-pink mochi blob with twin antennae.",
    },
    {
        "id": "kelp",
        "name": "Kelp",
        "color": "#8FE3B0",
        "shape": "tall",
        "pattern": "stripes",
        "blurb": "A tall, narrow minty-green blob with tide-pool stripes.",
    },
    {
        "id": "ember",
        "name": "Ember",
        "color": "#FFA36B",
        "shape": "teardrop",
        "pattern": "spots",
        "blurb": "A flame-shaped teardrop blob with a curly antenna.",
    },
    {
        "id": "nocturne",
        "name": "Nocturne",
        "color": "#6B7FE3",
        "shape": "horned",
        "pattern": "stars",
        "blurb": "A deep indigo blob with little horns, dusted with stars.",
    },
    {
        "id": "honeydew",
        "name": "Honeydew",
        "color": "#D9E36B",
        "shape": "round",
        "pattern": "plain",
        "blurb": "A cheerful chartreuse blob, plain and bright.",
    },
    {
        "id": "coral",
        "name": "Coral",
        "color": "#FF7F7F",
        "shape": "chubby",
        "pattern": "stripes",
        "blurb": "A round, chubby coral-red blob with tiny reef horns.",
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
