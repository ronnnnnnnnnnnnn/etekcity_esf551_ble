__version__ = "0.4.0-beta.5"

def _parse_version_info(version_str: str) -> tuple[int, ...]:
    """Parse version string into tuple of integers, handling suffixes."""
    import re

    base_version = version_str.split('+')[0]
    match = re.match(r'^(\d+(?:\.\d+)*)', base_version)
    if not match:
        return tuple()
    return tuple(int(part) for part in match.group(1).split('.'))

__version_info__ = _parse_version_info(__version__)
