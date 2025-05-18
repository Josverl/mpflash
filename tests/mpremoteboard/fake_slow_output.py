"""This script creates fake output to thest error handling of the mpremoteboard module."""

import time

OUT = """\
Error: Some fake error message

  File "<stdin>", line 1

INFO: Some fake info message
this is some output 
this is some more output
"""
delay = 0.1
for l in OUT.splitlines():
    time.sleep(delay)
    delay += 0.1
    print(l)

for n in range(100):
    time.sleep(0.1)
    print(f"this is some more output {n}")
