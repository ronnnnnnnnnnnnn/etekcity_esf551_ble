__version__ = "0.3.4"

def _parse_version_info(version_str: str) -> tuple:
    """Parse version string into tuple of integers, handling post-release versions."""
    import re
    # Remove version suffixes (post, dev, alpha, beta, rc, etc.) and local version identifiers
    # Examples: "0.3.2.post1" -> "0.3.2", "1.2.3.dev0" -> "1.2.3", "2.0.0+local" -> "2.0.0"
    base_version = re.sub(r'\.(post|dev|a|alpha|b|beta|rc|c|pre|preview)\d+.*$', '', version_str)
    base_version = base_version.split('+')[0]  # Remove local version identifier
    # Split by '.' and convert to integers
    parts = base_version.split('.')
    return tuple(map(int, parts))

__version_info__ = _parse_version_info(__version__)
