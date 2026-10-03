"""Built-in backup providers; importing this package registers them.

Each provider module calls :func:`mpflash.backup.registry.register` at import
time and is imported here. Providers are added by later phases of the backup
epic (VFS, ESP raw flash, ...).
"""
