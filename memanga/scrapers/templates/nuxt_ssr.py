"""
Template for Nuxt SSR single-manga sites with assets CDN.

Sites like dddmanga.com, chainsawdevil.com, jjkaisen.com, etc.
All share: sequential chapters, assets CDN for images, single manga per site.

Subclass config attributes:
    BASE_URL: str        - Site URL (e.g., "https://dddmanga.com")
    ASSETS_URL: str      - CDN base (e.g., "https://assets.dddmanga.com/dandadan")
    MANGA_TITLE: str     - Display title (e.g., "Dandadan")
    SEARCH_KEYWORDS: list - Strings that trigger search match
    FALLBACK_MAX: int    - Chapter count fallback if detection fails
"""

import re
from typing import List
from pathlib import Path
from ..base import BaseScraper, Chapter, Manga


class NuxtSSRScraper(BaseScraper):
    """Template for Nuxt SSR single-manga sites with sequential chapters."""

    BASE_URL: str = ""
    ASSETS_URL: str = ""
    MANGA_TITLE: str = ""
    SEARCH_KEYWORDS: list = []
    FALLBACK_MAX: int = 200

    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.BASE_URL,
        })

    def search(self, query: str) -> List[Manga]:
        """Search returns the single manga if query matches keywords."""
        q = query.lower()
        for kw in self.SEARCH_KEYWORDS:
            if kw.lower() in q or q in kw.lower():
                return [Manga(
                    title=self.MANGA_TITLE,
                    url=self.BASE_URL,
                )]
        return []

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapters by detecting max chapter from homepage."""
        try:
            resp = self._request(self.BASE_URL)

            # Try "Read Latest Chapter (N)" pattern
            match = re.search(r'Read Latest Chapter \((\d+)\)', resp.text)
            if match:
                max_chapter = int(match.group(1))
            else:
                # Fallback: find highest chapter number in links
                chapter_matches = re.findall(r'/chapter/(\d+)/', resp.text)
                if chapter_matches:
                    max_chapter = max(int(c) for c in chapter_matches)
                else:
                    max_chapter = self.FALLBACK_MAX
        except Exception:
            max_chapter = self.FALLBACK_MAX

        return [
            Chapter(
                number=str(i),
                title=f"Chapter {i}",
                url=f"{self.BASE_URL}/chapter/{i}/",
            )
            for i in range(1, max_chapter + 1)
        ]

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get page images from assets CDN."""
        try:
            resp = self._request(chapter_url)
        except Exception:
            return []

        # Extract chapter number from URL
        match = re.search(r'/chapter/(\d+)/', chapter_url)
        if not match:
            return []
        chapter_num = match.group(1)

        # Find images from assets CDN: assets.{domain}/{manga}/chapter-N/X.ext
        assets_escaped = re.escape(self.ASSETS_URL)
        img_matches = re.findall(
            rf'src="({assets_escaped}/chapter-{chapter_num}/\d+\.(?:jpeg|jpg|png|webp))"',
            resp.text
        )

        if img_matches:
            return list(dict.fromkeys(img_matches))

        # Fallback: any image from the assets domain (filter to image extensions)
        all_imgs = re.findall(
            rf'src="({assets_escaped}/[^"]+\.(?:jpeg|jpg|png|webp|gif))"',
            resp.text
        )
        return list(dict.fromkeys(all_imgs))

    def download_image(self, url: str, path: Path) -> bool:
        """Download image with Referer header."""
        try:
            response = self._request(url, headers={
                "Referer": self.BASE_URL,
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            })

            if len(response.content) < 1000:
                return False

            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                f.write(response.content)
            return True
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            return False
