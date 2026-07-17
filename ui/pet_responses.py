#!/usr/bin/env python3
"""pet_responses.py — canned, INSTANT reaction lines.

These fire for scenarios where waiting on the LLM (`pet_brain.PetBrain`)
would feel laggy or just isn't worth the round-trip: a window closing, or
the user picking the pet up and dragging it around. Picked via
`random.choice`, so each list stays large (50+) to avoid visible repeats.

Kept in the same goofy/harmless voice as `pet_brain.SYSTEM_PROMPT` (Pip is a
legless, tailless, furless lavender blob with tentacle arms + an antenna —
lines here avoid claiming anatomy it doesn't have).
"""

import random
import re

# --------------------------------------------------------------- window close
# {app} is substituted with a human-readable app name (see format_app_name).
WINDOW_CLOSE_TEMPLATES = [
    "Cya, {app}! *waves*",
    "Bye bye, {app}!",
    "Later, {app}! *tiny wave*",
    "{app} out! See ya!",
    "Poof! {app} is gone. Bye!",
    "Aw, {app} closed. *waves*",
    "*waves a tentacle* Bye {app}!",
    "{app}, off you go! Bye!",
    "Catch ya later, {app}!",
    "{app} vanished! *waves*",
    "Bye-bye {app}, wobble wobble!",
    "Ooh, {app} closed! Toodles!",
    "See ya, {app}! *bounces*",
    "{app} is done for now. Bye!",
    "*small wave* Bye {app}!",
    "Peace out, {app}!",
    "{app}, until next time!",
    "Farewell, {app}! *wiggles antenna*",
    "Whoosh, {app} is gone. Bye!",
    "{app} closed — I'll miss it a little!",
    "Aaand {app} is gone. Bye bye!",
    "*waves goodbye to {app}*",
    "{app}! Come back soon, bye!",
    "Adios, {app}!",
    "So long, {app}!",
    "{app} out the door! *waves*",
    "*happy wave* Bye {app}!",
    "{app} closed, I noticed that!",
    "Bloop! {app} disappeared. Bye!",
    "{app}, see you around!",
    "Tiny wave for {app}. Bye!",
    "{app} shut down. Cya!",
    "Whee, {app} is closing! Bye!",
    "{app}? Gone! *waves*",
    "Sayonara, {app}!",
    "{app} left the building. Bye!",
    "*wiggles* Bye {app}!",
    "{app} closed itself. Neat! Bye!",
    "Off you pop, {app}! Bye!",
    "{app}, that was fun. Bye!",
    "Ta-ta, {app}!",
    "*blob wave* Bye {app}!",
    "{app} window closed. *waves*",
    "Byeee {app}, come back later!",
    "{app} vanished into thin air! Bye!",
    "See ya next time, {app}!",
    "{app}, ciao!",
    "*tiny bounce and wave* Bye {app}!",
    "{app} is history. For now. Bye!",
    "Cheerio, {app}!",
    "{app} logged off my radar. Bye!",
    "Later gator, {app}!",
    "{app} disappeared! *waves happily*",
    "Bye {app}, that was quick!",
    "{app}'s closing up shop. Bye!",
]

# --------------------------------------------------------------- click + drag
DRAG_RESPONSES = [
    "Weeeee!",
    "Wheeee!",
    "Whoaaa, flying!",
    "*happy squish* Weee!",
    "Wobble wobble wheee!",
    "This is fun!",
    "Zoooom!",
    "Wheee, catch me!",
    "*giggles* Weee!",
    "Look at me go!",
    "Airborne blob!",
    "Wheeeee, again!",
    "*wobbles excitedly*",
    "Up up and away!",
    "Squish and fly!",
    "Whoosh!",
    "Yippee!",
    "This tickles!",
    "*flails tentacles happily*",
    "Fly little blob, fly!",
    "Wheee, new spot!",
    "Boing boing!",
    "*happy wobble noises*",
    "I'm flying!",
    "Zoom zoom zoom!",
    "*antenna flops around*",
    "Weeee, where are we going?",
    "This is the best!",
    "*wiggly excitement*",
    "Catch me if I fall!",
    "Wheee-hee-hee!",
    "Blob express, departing!",
    "*squishy giggles*",
    "So fast!",
    "Up we go!",
    "*tentacles waving in the wind*",
    "Yahoo!",
    "Wheee, dizzy blob!",
    "This is my favorite thing now!",
    "*happy wobble*",
    "Flying blob incoming!",
    "Wheeee, one more time!",
    "Onward!",
    "Blob liftoff!",
    "*jiggles happily*",
    "New view up here!",
    "Weee, hang on!",
    "*excited squish*",
    "This is thrilling!",
    "Wheeeeee!",
    "Blob on the move!",
    "*bounces along*",
    "Adventure time!",
    "Weee, again again!",
    "*giggly wobble*",
]

# App names as reported by WM_CLASS / process name are often terse or
# machine-y (e.g. "code", "chromium-browser", "org.gnome.TextEditor"). Map
# the common ones to something a person would actually call the app.
_APP_NAME_OVERRIDES = {
    "code": "VS Code",
    "code - oss": "VS Code",
    "vscodium": "VS Code",
    "firefox": "Firefox",
    "firefox-esr": "Firefox",
    "chromium": "Chromium",
    "chromium-browser": "Chromium",
    "google-chrome": "Chrome",
    "notepad": "Notepad",
    "gnome-terminal": "Terminal",
    "gnome-terminal-server": "Terminal",
    "konsole": "Konsole",
    "xterm": "Terminal",
    "explorer": "Explorer",
    "nautilus": "Files",
    "org.gnome.nautilus": "Files",
    "gedit": "Text Editor",
    "libreoffice": "LibreOffice",
    "soffice": "LibreOffice",
    "slack": "Slack",
    "discord": "Discord",
    "spotify": "Spotify",
}


def format_app_name(name):
    """Turn a raw app/process identifier into something readable, e.g.
    "notepad" -> "Notepad", "org.gnome.TextEditor" -> "Text Editor"."""
    if not name:
        return "that window"
    raw = str(name).strip()
    key = re.sub(r"\.exe$", "", raw, flags=re.IGNORECASE).strip().lower()
    if key in _APP_NAME_OVERRIDES:
        return _APP_NAME_OVERRIDES[key]
    # Reverse-DNS style class names (org.gnome.TextEditor) -> last segment,
    # then split CamelCase ("TextEditor" -> "Text Editor").
    if "." in raw and " " not in raw:
        key = raw.rsplit(".", 1)[-1]
        key = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", key).lower()
    key = re.sub(r"[-_]+", " ", key).strip()
    if not key or key in ("unknown", "none"):
        return "that window"
    return " ".join(w[:1].upper() + w[1:] for w in key.split())


def random_window_close_line(app_name):
    """One instant, non-LLM 'goodbye' line reacting to a window closing."""
    app = format_app_name(app_name)
    return random.choice(WINDOW_CLOSE_TEMPLATES).format(app=app)


def random_drag_line():
    """One instant, non-LLM line for when the user starts dragging the pet."""
    return random.choice(DRAG_RESPONSES)
