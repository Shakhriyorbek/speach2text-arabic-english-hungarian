"""
Settings that are true for THIS laptop only.

Copy this file to `config_local.py` and edit that copy. Anything you put there
overrides config.py, and it is never overwritten by an update — which is the
whole point: config.py belongs to the program, config_local.py belongs to the
machine.

The only setting most laptops need is the microphone. Find its number with:

    venv\\Scripts\\python -m subtitles.miccheck --list

Then uncomment the line below and put that number in.
"""

# The microphone. A number from the listing above — NOT the order Windows
# shows in its own Sound settings, which is different.
# MIC_DEVICE = 3

# Bigger or smaller subtitles on this particular projector.
# FONT_SIZE = 52

# Run without the GPU on this laptop, even though it is configured.
# ASR_LOCATION = "cpu"
# MT_LOCATION = "cpu"
# STREAMING_PARTIALS = False
