"""This script creates fake output to thest error handling of the mpremoteboard module."""

OUT = """\
Error: Some fake error message

  File "<stdin>", line 1

INFO  : Some fake info message
WARN  : some fake warning message
OK    : some fake done message
this is some output 
this is some more output
"""
for l in OUT.splitlines():
    print(l)
