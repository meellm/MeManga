"""
Omega Scans scraper - requires Playwright for JS rendering.
Site: https://omegascans.org
"""

import re
from typing import Optional
from .playwright_base import PlaywrightScraper
from bs4 import BeautifulSoup


class OmegaScansScraper(PlaywrightScraper):
    name = "OmegaScans"
    domains = ["omegascans.org"]
    base_url = "https://omegascans.org"

    def search(self, query: str) -> list[dict]:
        """Search for manga by title."""
        # OmegaScans doesn't have a search API, scrape the homepage
        # and filter by query
        url = self.base_url
        html = self._get_page_content(url, wait_time=3000)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        query_lower = query.lower()
        
        # Find series links with their titles
        for link in soup.select('a[href*="/series/"]'):
            href = link.get("href", "")
            if "/series/" in href and "/chapter" not in href:
                # Extract slug from href
                match = re.search(r"/series/([^/]+)", href)
                if not match:
                    continue
                    
                slug = match.group(1)
                
                # Get title - either from link text or convert slug
                text = link.get_text(strip=True)
                if text:
                    # Title might be concatenated with description, try to split
                    # Usually title is followed by description without space
                    title = text.split('\n')[0][:100]
                else:
                    # Convert slug to title: "solo-leveling" -> "Solo Leveling"
                    title = slug.replace("-", " ").title()
                
                # Check if query matches title or slug
                if query_lower in title.lower() or query_lower in slug.lower():
                    results.append({
                        "id": slug,
                        "title": title,
                        "url": f"{self.base_url}/series/{slug}",
                    })
        
        # Remove duplicates
        seen = set()
        unique_results = []
        for r in results:
            if r["id"] not in seen:
                seen.add(r["id"])
                unique_results.append(r)
        
        return unique_results[:20]

    def get_chapters(self, manga_id: str) -> list[dict]:
        """Get list of chapters for a manga."""
        url = f"{self.base_url}/series/{manga_id}"
        html = self._get_page_content(url, wait_time=3000)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        
        # Find chapter links - pattern: /series/{slug}/chapter-{num}
        for link in soup.select(f'a[href*="/series/{manga_id}/chapter"]'):
            href = link.get("href", "")
            text = link.get_text(strip=True)
            
            # Extract chapter number from URL
            match = re.search(r"/chapter-?([\d.]+)", href)
            if match:
                chapter_num = match.group(1)
                
                # Build chapter URL
                if href.startswith("http"):
                    chapter_url = href
                elif href.startswith("/"):
                    chapter_url = f"{self.base_url}{href}"
                else:
                    chapter_url = f"{self.base_url}/{href}"
                
                chapters.append({
                    "id": f"chapter-{chapter_num}",
                    "chapter": chapter_num,
                    "title": text or f"Chapter {chapter_num}",
                    "url": chapter_url,
                })
        
        # Remove duplicates and sort
        seen = set()
        unique_chapters = []
        for ch in chapters:
            if ch["id"] not in seen:
                seen.add(ch["id"])
                unique_chapters.append(ch)
        
        # Sort by chapter number (descending - newest first)
        def parse_chapter(ch):
            try:
                return float(ch["chapter"])
            except:
                return 0
        
        unique_chapters.sort(key=parse_chapter, reverse=True)
        return unique_chapters

    def get_chapter_images(self, manga_id: str, chapter_id: str) -> list[str]:
        """Get image URLs for a chapter."""
        # chapter_id format: "chapter-{num}"
        chapter_num = chapter_id.replace("chapter-", "")
        url = f"{self.base_url}/series/{manga_id}/chapter-{chapter_num}"
        return self.get_pages(url)

    def get_pages(self, chapter_url: str) -> list[str]:
        """Get all page image URLs for a chapter."""
        html = self._get_page_content(chapter_url, wait_time=4000)
        soup = BeautifulSoup(html, "html.parser")
        
        images = []
        
        # Find images from media.omegascans.org
        for img in soup.select("img"):
            src = img.get("src") or img.get("data-src") or ""
            if "media.omegascans.org" in src and "/uploads/" in src:
                if src not in images:
                    images.append(src)
        
        return images
