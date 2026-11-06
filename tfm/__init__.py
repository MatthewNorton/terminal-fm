"""Terminal FM's modules, split out of radio.py.

radio.py stays the entry point (the skill and the hooks run it) and keeps COMMANDS and main. It runs
as __main__, so nothing may `import radio`: that would load a second copy with its own config and
state. What it shares lives here, and the modules are imported as modules, never their names
(`from tfm import core`, then `core.ROOT`), so a test that patches a name in its module reaches
every caller. tests/test_layout.py checks both rules.
"""
