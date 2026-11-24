"""Default: MCP service. Also accepts doctor/tools/open/snapshot/call."""
import sys
from launcher import launch

if __name__=='__main__':raise SystemExit(launch('browser',sys.argv[1:]))
