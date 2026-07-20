"""
Update checker for Fan Hub and OpenRGB.

Queries GitHub / Codeberg release APIs asynchronously (QThread) so the UI
never blocks. Each check is cached for one hour so repeat visits to the
Settings tab don't hammer the APIs.

Fan Hub releases:   https://github.com/bobbycomet/Fan-Hub/releases
OpenRGB releases:   https://codeberg.org/OpenRGB/OpenRGB/releases
"""
import json
import logging
import re
import time
from typing import Optional, Tuple
from urllib.request import urlopen, Request
from urllib.error import URLError

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger('fanhub.updates')

# ── Constants ─────────────────────────────────────────────────────────────────

FANHUB_CURRENT_VERSION = '1.6.0'

FANHUB_API_URL    = 'https://api.github.com/repos/bobbycomet/Fan-Hub/releases/latest'
FANHUB_RELEASES   = 'https://github.com/bobbycomet/Fan-Hub/releases'
FANHUB_APPIMAGE   = 'https://github.com/bobbycomet/Fan-Hub/releases/download/V{ver}/FanHub-{ver}-x86_64.AppImage'
FANHUB_TARBALL    = 'https://github.com/bobbycomet/Fan-Hub/releases/download/V{ver}/fanhub_v{ver}.tar.gz'
FANHUB_DEB        = 'https://github.com/bobbycomet/Fan-Hub/releases/download/V{ver}/fanhub.deb'

OPENRGB_API_URL   = 'https://codeberg.org/api/v1/repos/OpenRGB/OpenRGB/releases?limit=1'
OPENRGB_SITE      = 'https://openrgb.org'
OPENRGB_RELEASES  = 'https://codeberg.org/OpenRGB/OpenRGB/releases'

# Known RC1 assets (fallback when API parse fails)
OPENRGB_APPIMAGE_FALLBACK = (
    'https://codeberg.org/OpenRGB/OpenRGB/releases/download/'
    'release_candidate_1.0rc3/'
    'OpenRGB_1.0rc3_x86_64_6fbcf62.AppImage'
)
OPENRGB_DEB_FALLBACK = (
    'https://codeberg.org/OpenRGB/OpenRGB/releases/download/'
    'release_candidate_1.0rc3/'
    'openrgb_1.0rc3_amd64_bookworm_6fbcf62.deb'
)

# Cache TTL: one hour
_CACHE_TTL = 3600


# ── Version comparison ────────────────────────────────────────────────────────

def _parse_version(v: str) -> Tuple[int, ...]:
    """
    Turn a version string into a comparable tuple of ints.

    Rules:
    - Strips leading 'v'/'V'
    - Strips Debian revision suffix (hyphen-integer at end): '1.6.0' → '1.6.0'
    - Ignores pre-release alpha labels for ordering purposes
    - '1.0rc3' → (1, 0) — rc suffix treated as 0 patch

    Examples:
      '1.6.0'    → (1, 6, 0)
      '1.6.0-01' → (1, 6, 0)   ← Debian revision stripped
      'V1.6.1'   → (1, 6, 1)
      '1.0rc3'   → (1, 0)
      '2.0.0'    → (2, 0, 0)
    """
    v = v.lstrip('vV').strip()
    # Strip Debian-style revision: trailing -<digits> only (not pre-release like -alpha)
    v = re.sub(r'-\d+$', '', v)
    # Remove pre-release label (rc, alpha, beta, ...) for numeric ordering
    v = re.sub(r'[a-zA-Z].*', '', v)
    parts = re.split(r'[.\-_]', v)
    result = []
    for p in parts:
        try:
            result.append(int(p))
        except ValueError:
            break
    return tuple(result) or (0,)


def is_newer(latest: str, current: str) -> bool:
    """Return True if latest > current."""
    return _parse_version(latest) > _parse_version(current)


# ── Data objects ──────────────────────────────────────────────────────────────

class ReleaseInfo:
    """Holds the result of a single release API check."""
    __slots__ = ('name', 'version', 'url', 'assets', 'error', 'checked_at')

    def __init__(self, name: str, version: str = '', url: str = '',
                 assets: Optional[dict] = None, error: str = ''):
        self.name       = name
        self.version    = version
        self.url        = url
        self.assets     = assets or {}   # {label: download_url}
        self.error      = error
        self.checked_at = time.time()

    @property
    def ok(self) -> bool:
        return bool(self.version) and not self.error


# ── Cache ─────────────────────────────────────────────────────────────────────

_cache: dict[str, ReleaseInfo] = {}


def _cached(key: str) -> Optional[ReleaseInfo]:
    info = _cache.get(key)
    if info and (time.time() - info.checked_at) < _CACHE_TTL:
        return info
    return None


def _store(key: str, info: ReleaseInfo):
    _cache[key] = info


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _get_json(url: str, timeout: int = 8) -> Optional[dict]:
    try:
        req = Request(url, headers={
            'User-Agent': f'FanHub/{FANHUB_CURRENT_VERSION}',
            'Accept': 'application/json',
        })
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            data = json.loads(raw)
            # Codeberg returns a list for /releases?limit=1
            if isinstance(data, list):
                return data[0] if data else None
            return data
    except URLError as e:
        logger.debug(f"HTTP {url}: {e}")
    except Exception as e:
        logger.debug(f"JSON parse {url}: {e}")
    return None


# ── Per-project checkers ──────────────────────────────────────────────────────

def check_fanhub() -> ReleaseInfo:
    """Fetch the latest Fan Hub release from GitHub."""
    cached = _cached('fanhub')
    if cached:
        return cached

    data = _get_json(FANHUB_API_URL)
    if not data:
        info = ReleaseInfo('Fan Hub', error='Could not reach GitHub')
        _store('fanhub', info)
        return info

    tag  = data.get('tag_name', '')           # e.g. 'V1.5.6'
    ver  = tag.lstrip('vV')                   # e.g. '1.5.6'
    page = data.get('html_url', FANHUB_RELEASES)

    # Build download URLs from the tag (may differ from the template if user
    # named the release differently — prefer actual asset URLs from API)
    assets = {}
    for asset in data.get('assets', []):
        name = asset.get('name', '').lower()
        url  = asset.get('browser_download_url', '')
        if not url:
            continue
        if name.endswith('.appimage'):
            assets['AppImage'] = url
        elif name.endswith('.tar.gz'):
            assets['Tarball (.tar.gz)'] = url
        elif name.endswith('.deb'):
            assets['Debian (.deb)'] = url

    # Fill in template URLs for any missing asset types
    if 'AppImage' not in assets and ver:
        assets['AppImage'] = FANHUB_APPIMAGE.format(ver=ver)
    if 'Tarball (.tar.gz)' not in assets and ver:
        assets['Tarball (.tar.gz)'] = FANHUB_TARBALL.format(ver=ver)
    if 'Debian (.deb)' not in assets and ver:
        assets['Debian (.deb)'] = FANHUB_DEB.format(ver=ver)

    info = ReleaseInfo('Fan Hub', version=ver, url=page, assets=assets)
    _store('fanhub', info)
    return info


def check_openrgb() -> ReleaseInfo:
    """Fetch the latest OpenRGB release from Codeberg."""
    cached = _cached('openrgb')
    if cached:
        return cached

    data = _get_json(OPENRGB_API_URL)
    if not data:
        # Return known RC1 assets as fallback so user still has somewhere to go
        info = ReleaseInfo(
            'OpenRGB',
            version='1.0rc3',
            url=OPENRGB_RELEASES,
            assets={
                'AppImage (x86_64)': OPENRGB_APPIMAGE_FALLBACK,
                'Debian (.deb)':     OPENRGB_DEB_FALLBACK,
                'All releases':      OPENRGB_RELEASES,
            },
            error='Could not reach Codeberg — showing last known release',
        )
        _store('openrgb', info)
        return info

    tag  = data.get('tag_name', '')
    ver  = tag.lstrip('vV').replace('release_candidate_', '')
    page = data.get('html_url', OPENRGB_RELEASES)

    assets = {}
    for asset in data.get('assets', []):
        name = asset.get('name', '')
        url  = asset.get('browser_download_url', '')
        if not url:
            continue
        nl = name.lower()
        if nl.endswith('.appimage'):
            assets[f'AppImage ({name})'] = url
        elif nl.endswith('.deb'):
            assets[f'Debian ({name})'] = url
        elif nl.endswith('.tar.gz') or nl.endswith('.zip'):
            assets[f'Archive ({name})'] = url

    if not assets:
        assets = {
            'AppImage (x86_64)': OPENRGB_APPIMAGE_FALLBACK,
            'Debian (.deb)':     OPENRGB_DEB_FALLBACK,
        }

    assets['All releases'] = OPENRGB_RELEASES
    assets['OpenRGB website'] = OPENRGB_SITE

    info = ReleaseInfo('OpenRGB', version=ver, url=page, assets=assets)
    _store('openrgb', info)
    return info


def invalidate_cache():
    """Force next check to hit the network (call after user requests refresh)."""
    _cache.clear()


# ── QThread worker ────────────────────────────────────────────────────────────

class UpdateCheckWorker(QThread):
    """
    Runs both update checks off the UI thread.
    Emits fanhub_result and openrgb_result when each finishes.
    """
    fanhub_result  = pyqtSignal(object)   # ReleaseInfo
    openrgb_result = pyqtSignal(object)   # ReleaseInfo

    def run(self):
        try:
            self.fanhub_result.emit(check_fanhub())
        except Exception as e:
            logger.error(f"Fan Hub update check: {e}")
            self.fanhub_result.emit(
                ReleaseInfo('Fan Hub', error=str(e)))
        try:
            self.openrgb_result.emit(check_openrgb())
        except Exception as e:
            logger.error(f"OpenRGB update check: {e}")
            self.openrgb_result.emit(
                ReleaseInfo('OpenRGB', error=str(e)))
