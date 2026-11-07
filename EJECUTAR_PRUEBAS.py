"""Ejecuta las pruebas automatizadas del proyecto."""
import os
import sys
import unittest
from pathlib import Path

project_dir = Path(__file__).resolve().parent
os.chdir(project_dir)
sys.path.insert(0, str(project_dir))
suite = unittest.defaultTestLoader.discover(str(project_dir), pattern="test_*.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
