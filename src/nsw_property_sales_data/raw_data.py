import logging
import shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import urlopen


logger = logging.getLogger(__name__)


class LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.hrefs.append(value)


def fetch_zip_addresses() -> list[str]:
    with urlopen(
        "https://valuation.property.nsw.gov.au/embed/propertySalesInformation"
    ) as r:
        html = r.read().decode()
    p = LinkCollector()
    p.feed(html)
    return [h for h in p.hrefs if h.endswith(".zip")]


def unsynced_zips(available_zips: list[str], loaded: set[str]) -> list[str]:
    return [url for url in available_zips if url.rsplit("/", 1)[-1] not in loaded]


def download_file_from_url(url: str, target: Path) -> None:
    with urlopen(url) as r, open(target, "wb") as f:
        shutil.copyfileobj(r, f)


def download_unsynced(pending: list[str], cache_dir: Path) -> list[Path]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []
    for url in pending:
        target = cache_dir / url.rsplit("/", 1)[-1]
        if target.exists():
            logger.debug("Skipping %s (already cached)", target.name)
            continue
        logger.debug("Downloading %s", url)
        download_file_from_url(url, target)
        downloaded.append(target)
    return downloaded
