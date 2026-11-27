"""Shared pytest fixtures/path setup for the PENT-03 offline suite.

Adds ``lab/scripts`` to ``sys.path`` so the modules import flatly (``import
adb``) exactly as they do on the controller, and keeps the whole suite offline:
no device, no network, no root.
"""
import os
import sys

SCRIPTS = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
