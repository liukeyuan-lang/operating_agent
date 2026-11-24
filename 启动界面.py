"""Run with python on Windows, python3 on macOS/Linux."""
import sys
from launcher import launch

if __name__=='__main__':raise SystemExit(launch('ui',sys.argv[1:]))
