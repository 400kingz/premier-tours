"""Zero-touch intake — pull listing photos from a URL or a street address.

Supported sources:
  - Address (HomeHarvest): scrape realtor.com's full gallery by street address
  - Google Drive share links (publicly shared files)
  - Generic listing pages: og:image + high-res <img> tags

Note: major portals (Zillow, Redfin) gate scraping behind anti-bot walls and
their ToS prohibit it — those URLs will typically fail here. The honest paths
are direct photo upload, Drive links, an address (HomeHarvest), or an MLS/IDX
feed. HomeHarvest returns full galleries for *active* listings; sold/off-market
listings often expose only one or two photos.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path

import httpx

from app.config import get_settings

_UA = "PremierHomeTours/1.0 (+listing intake)"
_IMG_EXT = re.compile(r"\.(jpe?g|png|webp)(\?|$)", re.I)
_MIN_BYTES = 60_000          # skip thumbnails/icons
_MAX_PHOTOS = 12
# HomeHarvest serves rdcpix thumbnails (e.g. ...-w480_h360_x2.webp?w=1080); the
# "-o.jpg" rendition is the largest original realtor.com exposes.
_RDCPIX_RENDITION = re.compile(r"-w\d+_h\d+(?:_x\d+)?\.\w+$")


class IntakeError(RuntimeError):
    pass


def _drive_file_id(url: str) -> str | None:
    for pat in (r"/file/d/([\w-]{20,})", r"[?&]id=([\w-]{20,})"):
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


async def _download(client: httpx.AsyncClient, url: str, dest_dir: Path, idx: int) -> Path | None:
    try:
        r = await client.get(url, timeout=30, follow_redirects=True)
        r.raise_for_status()
        if len(r.content) < _MIN_BYTES or not r.headers.get("content-type", "").startswith("image/"):
            return None
        ext = {
            "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"
        }.get(r.headers["content-type"].split(";")[0], ".jpg")
        out = dest_dir / f"{idx}{ext}"
        out.write_bytes(r.content)
        return out
    except httpx.HTTPError:
        return None


async def fetch_photos_from_url(url: str, tour_id: str) -> list[Path]:
    """Download listing photos from a URL into the local upload dir."""
    settings = get_settings()
    dest = settings.upload_dir / tour_id
    dest.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(headers={"User-Agent": _UA}) as client:
        # Google Drive file
        file_id = _drive_file_id(url) if "drive.google.com" in url else None
        if file_id:
            p = await _download(
                client, f"https://drive.google.com/uc?export=download&id={file_id}",
                dest, 0,
            )
            if p:
                return [p]
            raise IntakeError(
                "Could not download from Drive — make sure the file is shared "
                "as 'anyone with the link'"
            )

        # Generic listing page
        try:
            r = await client.get(url, timeout=30, follow_redirects=True)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise IntakeError(
                f"Could not fetch listing page ({e}). Portals like Zillow block "
                "automated access — upload photos directly or use a Drive link."
            ) from None

        html = r.text
        candidates: list[str] = []
        candidates += re.findall(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html
        )
        candidates += [
            u for u in re.findall(r'<img[^>]+src=["\']([^"\']+)', html)
            if _IMG_EXT.search(u)
        ]
        # De-dupe preserving order, absolutize
        seen: set[str] = set()
        urls: list[str] = []
        for u in candidates:
            u = httpx.URL(url).join(u).human_repr()
            if u not in seen:
                seen.add(u)
                urls.append(u)

        photos: list[Path] = []
        for i, u in enumerate(urls[: _MAX_PHOTOS * 3]):
            if len(photos) >= _MAX_PHOTOS:
                break
            p = await _download(client, u, dest, len(photos))
            if p:
                photos.append(p)

        if not photos:
            raise IntakeError(
                "No usable high-res photos found at that URL. Upload photos "
                "directly or share a Google Drive link."
            )
        return photos


def _maximize_rdcpix(url: str) -> str:
    """Rewrite an rdcpix thumbnail URL to its largest original rendition."""
    if "rdcpix.com" not in url:
        return url
    url = url.split("?", 1)[0]                       # drop ?w=…&q=… downscale
    return _RDCPIX_RENDITION.sub("-o.jpg", url)


def _homeharvest_photo_urls(address: str) -> tuple[list[str], str]:
    """Return (photo_urls, status) for the best address match. Blocking."""
    from homeharvest import scrape_property   # lazy: optional heavy dep

    # Active listings carry the full gallery; fall back through other states so
    # a sold/pending home still yields whatever photos remain.
    for listing_type in ("for_sale", "pending", "sold", "for_rent"):
        try:
            df = scrape_property(
                location=address,
                listing_type=listing_type,
                limit=5,
                extra_property_data=True,
            )
        except Exception:
            continue
        if df is None or len(df) == 0:
            continue
        row = df.iloc[0]                              # closest address match
        urls: list[str] = []
        primary = row.get("primary_photo")
        if primary and str(primary) != "nan":
            urls.append(str(primary))
        alt = row.get("alt_photos")
        if alt and str(alt) != "nan":
            urls += [u.strip() for u in str(alt).split(",") if u.strip()]
        # De-dupe by the photo's stable rdcpix id, keep max rendition.
        seen: set[str] = set()
        maxed: list[str] = []
        for u in urls:
            big = _maximize_rdcpix(u)
            key = re.sub(r"-[wo].*$", "", big)
            if key not in seen:
                seen.add(key)
                maxed.append(big)
        if maxed:
            return maxed, str(row.get("status") or "")
    return [], ""


async def fetch_photos_via_address(address: str, tour_id: str) -> list[Path]:
    """Scrape listing photos for a street address via HomeHarvest (realtor.com)."""
    try:
        urls, status = await asyncio.to_thread(_homeharvest_photo_urls, address)
    except ImportError as e:
        raise IntakeError(
            "Address intake needs the 'homeharvest' package "
            "(pip install homeharvest)."
        ) from e

    if not urls:
        raise IntakeError(
            f"No listing found for '{address}'. Check the address, or upload "
            "photos / share a Drive link instead."
        )

    settings = get_settings()
    dest = settings.upload_dir / tour_id
    dest.mkdir(parents=True, exist_ok=True)

    photos: list[Path] = []
    async with httpx.AsyncClient(headers={"User-Agent": _UA}) as client:
        for u in urls[:_MAX_PHOTOS]:
            p = await _download(client, u, dest, len(photos))
            if p:
                photos.append(p)

    if not photos:
        raise IntakeError(
            f"Found a listing for '{address}' but its photos could not be "
            "downloaded (they may have been removed)."
        )
    if status.upper() == "SOLD" and len(photos) <= 2:
        # Surfaced, not raised — caller still gets the photo(s) we did find.
        pass
    return photos


def save_uploaded_photo(tour_id: str, filename: str, content: bytes) -> Path:
    settings = get_settings()
    dest = settings.upload_dir / tour_id
    dest.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        raise IntakeError(f"Unsupported file type: {ext}")
    out = dest / f"{uuid.uuid4().hex[:8]}{ext}"
    out.write_bytes(content)
    return out
