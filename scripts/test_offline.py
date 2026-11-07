"""Run synthetic Python tests with external socket connections prohibited."""

import os
from pathlib import Path
import socket
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
for name in list(os.environ):
    if name.startswith(('TOOL_OFFER_', 'FAHCE_', 'AGENTVERSE_', 'ASI1_', 'ASI_ONE_', 'OPENAI_', 'CLOUDFLARE_', 'AWS_')):
        os.environ.pop(name)
original_connect = socket.socket.connect
original_connect_ex = socket.socket.connect_ex


def connect(connection, address, original=original_connect):
    if isinstance(address, tuple) and address[0] not in ('localhost', '127.0.0.1', '::1'):
        raise AssertionError('External network disabled in judging tests')
    return original(connection, address)


socket.socket.connect = connect
socket.socket.connect_ex = lambda connection, address: connect(connection, address, original_connect_ex)
suite = unittest.defaultTestLoader.discover('tests', pattern='test_*.py')
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
