"""Tooling for the whole-France GTFS benchmark of raptor-kmp.

Builds a catalogue of French GTFS feeds, downloads their latest versions, merges them into
nested tiers (métropole ⊂ région ⊂ France) and drives the pipeline over the result. See
benchmark/README.md for the full run.
"""
