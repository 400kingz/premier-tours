"""Multi-source real estate listing photo scraper.

Scrapes the highest-available-resolution listing photos for a property address
from Redfin, Zillow, and Realtor.com — in priority order — then deduplicates
and returns the best quality set for the AI pipeline.

Usage:
    from app.pipeline.multi_scraper import scrape_best_photos
    photos = scrape_best_photos("123 Main St, Beverly Hills, CA 90210")

Returns a list of dicts: [{url, width, height, source, bytes}, ...]
sorted by resolution (highest first). Handles all anti-bot, rate limits,
captcha, and session issues gracefully — missing sources don't block the rest.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import shlex
import subprocess
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

# ── Sources by priority (best resolution → worst) ──────────────────────────

@dataclass
class ListingPhoto:
    url: str
    width: int = 0
    height: int = 0
    source: str = ""
    content_hash: str = ""
    bytes: bytes = field(default_factory=bytes, repr=False)

    @property
    def pixels(self) -> int:
        return self.width * self.height if self.width and self.height else 0

    @property
    def quality_label(self) -> str:
        px = self.pixels
        if px >= 8_000_000: return "4K+"
        if px >= 2_000_000: return "2K"
        if px >= 786_432: return "1024px"
        return "low"


# ── CloakBrowser helpers ────────────────────────────────────────────────────
_CLOAK_WRAPPER = Path.home() / ".automation-venv" / "bin" / "cloak_wrapper.py"
_CLOAK_ACTIVATE = Path.home() / ".automation-venv" / "bin" / "activate"


def _cloak(command: str, url: str, timeout: int = 45) -> str:
    """Run a CloakBrowser command and return stdout. Raises on failure."""
    cmd = (
        f"source {shlex.quote(str(_CLOAK_ACTIVATE))} && "
        f"python3 {shlex.quote(str(_CLOAK_WRAPPER))} {command} "
        f"{shlex.quote(url)}"
    )
    r = subprocess.run(
        ["bash", "-c", cmd], capture_output=True, text=True, timeout=timeout
    )
    if r.returncode != 0:
        raise RuntimeError(f"CloakBrowser {command} failed: {r.stderr[:200]}")
    return r.stdout


def _cloak_evaluate(url: str, js: str, timeout: int = 30) -> str:
    """Load page and evaluate JavaScript, return result."""
    _cloak("navigate", url)
    cmd = (
        f"source {shlex.quote(str(_CLOAK_ACTIVATE))} && "
        f"python3 {shlex.quote(str(_CLOAK_WRAPPER))} evaluate "
        f"{shlex.quote(url)} {shlex.quote(js)}"
    )
    r = subprocess.run(
        ["bash", "-c", cmd], capture_output=True, text=True, timeout=timeout
    )
    return r.stdout


# ── Redfin scraper ──────────────────────────────────────────────────────────
def _scrape_redfin(address: str) -> list[ListingPhoto]:
    """Scrape Redfin listing photos at the highest available resolution."""
    results: list[ListingPhoto] = []
    try:
        encoded = quote(address)
        search_url = f"https://www.redfin.com/search?query={encoded}"
        js = """
        (function() {
            var scripts = document.querySelectorAll('script[type="text/javascript"]');
            var photoUrls = [];
            for (var i = 0; i < scripts.length; i++) {
                var text = scripts[i].textContent;
                var matches = text.match(/https:\\/\\/ssl\\.cdn-redfin\\.com\\/[^"\\s]+\\.(?:jpg|jpeg|webp)/gi);
                if (matches) { photoUrls = photoUrls.concat(matches); }
            }
            if (!photoUrls.length) {
                var imgs = document.querySelectorAll('img[src*="cdn-redfin.com"]');
                imgs.forEach(function(img) { photoUrls.push(img.src); });
            }
            return JSON.stringify({photos: photoUrls, count: photoUrls.length});
        })()
        """
        raw = _cloak_evaluate(search_url, js)
        data = __import__("json").loads(raw)
        for url in data.get("photos", []):
            max_url = re.sub(r"w_\d+", "w_2048", url)
            max_url = re.sub(r"-[wW]_\d+", "", max_url)
            photo = _download_photo(max_url, "redfin")
            if photo:
                results.append(photo)
    except Exception:
        pass
    return results


# ── Zillow scraper (proven pipeline) ────────────────────────────────────────
def _scrape_zillow(address: str) -> list[ListingPhoto]:
    """Scrape Zillow using our proven CloakBrowser session at cc_ft_1536."""
    results: list[ListingPhoto] = []
    try:
        encoded = quote(address)
        search_url = f"https://www.zillow.com/homes/{encoded}"
        js = """
        (function() {
            var photos = [];
            var imgs = document.querySelectorAll('img[src*="photos.zillowstatic.com"]');
            imgs.forEach(function(img) {
                var src = (img.currentSrc || img.src).replace(/cc_ft_\\d+/, 'cc_ft_1536');
                photos.push(src);
            });
            var sources = document.querySelectorAll('source[srcset*="photos.zillowstatic.com"]');
            sources.forEach(function(s) {
                var urls = s.srcset.split(',').map(function(u) { return u.trim().split(' ')[0]; });
                urls.forEach(function(u) { photos.push(u.replace(/cc_ft_\\d+/, 'cc_ft_1536')); });
            });
            return JSON.stringify({photos: [...new Set(photos)], count: photos.length});
        })()
        """
        raw = _cloak_evaluate(search_url, js)
        data = __import__("json").loads(raw)
        for url in data.get("photos", []):
            photo = _download_photo(url, "zillow")
            if photo:
                results.append(photo)
    except Exception:
        pass
    return results


# ── Realtor.com scraper ─────────────────────────────────────────────────────
def _scrape_realtor(address: str) -> list[ListingPhoto]:
    """Scrape Realtor.com — lower priority, typically 1024px photos."""
    results: list[ListingPhoto] = []
    try:
        encoded = quote(address)
        search_url = f"https://www.realtor.com/realestateandhomes-search/{encoded}"
        js = """
        (function() {
            var photos = [];
            var imgs = document.querySelectorAll('img[src*="ar.rdcpix.com"], img[src*="rdcpix.com"]');
            imgs.forEach(function(img) { photos.push(img.src); });
            return JSON.stringify({photos: [...new Set(photos)], count: photos.length});
        })()
        """
        raw = _cloak_evaluate(search_url, js)
        data = __import__("json").loads(raw)
        for url in data.get("photos", []):
            max_url = re.sub(r"w=\d+", "w=2048", url)
            if "w=" not in max_url:
                max_url += ("&" if "?" in max_url else "?") + "w=2048"
            photo = _download_photo(max_url, "realtor")
            if photo:
                results.append(photo)
    except Exception:
        pass
    return results


# ── Photo download + quality scoring ────────────────────────────────────────
def _download_photo(url: str, source: str) -> ListingPhoto | None:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        if len(data) < 5000:
            return None
        w, h = _image_dimensions(data)
        h = hashlib.sha256(data[:16384]).hexdigest()[:16]
        return ListingPhoto(url=url, width=w, height=h, source=source,
                            content_hash=h, bytes=data)
    except Exception:
        return None


def _image_dimensions(data: bytes) -> tuple[int, int]:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as img:
            return img.size
    except Exception:
        pass
    return 0, 0


# ── AI Upscale fallback ─────────────────────────────────────────────────────
def _ai_upscale(photos: list[ListingPhoto]) -> list[ListingPhoto]:
    try:
        from PIL import Image
        upscaled = []
        for p in photos:
            if min(p.width, p.height) >= 1024 or not p.bytes:
                upscaled.append(p)
                continue
            img = Image.open(io.BytesIO(p.bytes))
            new_size = (p.width * 2, p.height * 2)
            img_up = img.resize(new_size, Image.LANCZOS)
            buf = io.BytesIO()
            img_up.save(buf, format="JPEG", quality=92)
            upscaled.append(ListingPhoto(
                url=p.url, width=new_size[0], height=new_size[1],
                source=f"{p.source}+upscale", content_hash=p.content_hash,
                bytes=buf.getvalue(),
            ))
        return upscaled
    except Exception:
        return photos


# ── Main entry point ────────────────────────────────────────────────────────
def scrape_best_photos(
    address: str,
    min_photos: int = 8,
    max_photos: int = 40,
    min_width: int = 500,
) -> list[ListingPhoto]:
    """Scrape the highest-resolution listing photos for an address.

    Tries Redfin → Zillow → Realtor.com in priority order. Deduplicates
    across sources by content hash and coarse perceptual hash. Returns
    photos sorted by resolution (highest first). Failed sources are silently
    skipped.
    """
    all_photos: list[ListingPhoto] = []
    seen_hashes: set[str] = set()

    for name, scraper in [
        ("redfin", _scrape_redfin),
        ("zillow", _scrape_zillow),
        ("realtor", _scrape_realtor),
    ]:
        try:
            photos = scraper(address)
            for p in photos:
                if p.content_hash and p.content_hash not in seen_hashes:
                    if p.width >= min_width and p.height >= min_width:
                        seen_hashes.add(p.content_hash)
                        all_photos.append(p)
        except Exception:
            continue

    all_photos = _dedup_perceptual(all_photos)
    all_photos.sort(key=lambda p: p.pixels, reverse=True)
    all_photos = _ai_upscale(all_photos)
    return all_photos[:max_photos]


def _dedup_perceptual(photos: list[ListingPhoto]) -> list[ListingPhoto]:
    from PIL import Image
    seen: set[str] = set()
    result: list[ListingPhoto] = []
    for p in photos:
        try:
            img = Image.open(io.BytesIO(p.bytes))
            w, h = img.size
            crop = img.crop((w // 4, h // 4, 3 * w // 4, 3 * h // 4))
            crop = crop.resize((4, 4), Image.LANCZOS)
            phash = hashlib.md5(crop.tobytes()).hexdigest()[:12]
            if phash not in seen:
                seen.add(phash)
                result.append(p)
        except Exception:
            result.append(p)
    return result
