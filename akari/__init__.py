"""akari internals.  Users edit main.py and fixtures.py one level up."""
import sys

# Keep __pycache__ folders out of the user's folder (the rig file is compiled on every load).
sys.dont_write_bytecode = True
