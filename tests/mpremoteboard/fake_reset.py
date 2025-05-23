"""This script creates fake output to thest error handling of the mpremoteboard module."""

import time

OUT = """\
boot.esp32: PRO CPU has been reset by WDT.
Error: Some fake error message

  File "<stdin>", line 1

INFO: Some fake info message
this is some output 
this is some more output
rst cause:1, boot mode:
this is some more output
"""
for l in OUT.splitlines():
    time.sleep(0.05)
    print(l)
