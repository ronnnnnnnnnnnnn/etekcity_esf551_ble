__version__ = "0.4.0-beta.3"
# Extract numeric version for version_info (PEP 440 compatible)
__version_info__ = tuple(map(int, __version__.split("-")[0].split(".")))
