"""Public error messages never contain terminal escape sequences or CLI advice."""

import re

ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
VERIFICATION = "YouTube verification required. Open this video on YouTube and finish signing in or verification, then use 'Use YouTube sign-in' in SaveIt4U and retry. YouTube may still restrict this request."


def clean_text(value):
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", ANSI.sub("", str(value)))[:2000]


def public_error(value):
    message = clean_text(value)
    if any(part in message.lower() for part in ("confirm you're not a bot", "confirm you’re not a bot", "verification required", "login required", "sign in to", "use --cookies")):
        return VERIFICATION
    return message
