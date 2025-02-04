import json
import multiprocessing as mp
import os
import urllib.parse
from pathlib import Path
from typing import Iterator, Sequence

import filetype
import requests
from natsort import natsorted

from .base import BaseChapter, BaseMetadata
from .comic import BaseComic

NUM_LEFT_PAD_DIGITS = 5
FILE_PADDING = f"0{NUM_LEFT_PAD_DIGITS}"
MD_METADATA_FILE = "md-metadata.json"


def async_download_image(
    data: tuple[str, Path | str, str | None, dict[str, str] | None]
) -> None:
    """
    Download an image from a URL to a destination folder, fixing the file extension if necessary.

    :param `data`: A tuple of the url, destination folder, filename, and headers.
    """
    url, dest_folder, filename, headers = data
    dest_folder = Path(dest_folder)

    name = filename or url.split("/")[-1]
    dest_file = dest_folder / name

    res = requests.get(url, headers=headers, timeout=5)
    res.raise_for_status()
    with open(dest_file, "wb") as file:
        file.write(res.content)

    # if the file extension is lying
    # rename it so epubcheck doesn't yell at us
    ext = filetype.guess(dest_file)
    if ext is not None and ext.extension in ["jpg", "png", "gif"]:
        dest_file.rename(dest_file.with_suffix(f".{ext.extension}"))


def download_images(
    urls: Sequence[str],
    dest_folder: Path | str,
    *,
    filestems: Sequence[str] | None = None,
    headers: dict[str, str] | None = None,
    threads: int = 1,
) -> Iterator[None]:
    """
    Download one or multiple URLs to a destination folder.
    Raises ValueError if the folder does not exist.

    :param `urls`: A list of URLs to download.
    :param `dest_folder`: The path to download files into.
    :param `filestems`: Specify the name of each downloaded file instead of the default.
    :param `headers`: Request headers
    :param `threads`: The number of processes to open
    :returns An iterator that yields `None` for each downloaded file.
    """
    dest_folder = Path(dest_folder)

    # attempt to create
    dest_folder.mkdir(exist_ok=True)

    # args to async_download
    map_pool: list[tuple[str, Path | str, str | None, dict[str, str] | None]] = []

    if filestems is None:
        filestems = [f"{i+1:FILE_PADDING}" for i in range(len(urls))]

    for url, stem in zip(urls, filestems, strict=True):
        _, ext = os.path.splitext(urllib.parse.urlparse(url).path)
        map_pool.append((url, dest_folder, f"{stem}{ext}", headers))

    with mp.Pool(threads) as pool:
        yield from pool.imap_unordered(async_download_image, map_pool)


def read_comic(path: Path | str) -> BaseComic:
    """
    Open a comic from a folder path.

    :param `path`: A folder containing `md-metadata.json`
    :returns A comic with metadata and chapter data of that folder
    :raises `FileNotFoundError` if `md-metadata.json` is not found.
    :raises `IOError` if the path does not exist.
    """
    path = Path(path)
    json_path = path / MD_METADATA_FILE

    if not path.exists():
        raise IOError(f"Path {path} does not exist")

    with open(json_path, "r", encoding="utf-8") as file:
        data = json.load(file)

    return BaseComic(
        BaseMetadata(**data["metadata"]),
        [BaseChapter(**c) for c in data["chapters"]],
    )


def parse_comic(path: Path | str, donor_comic: BaseComic | None = None) -> BaseComic:
    """
    Parse and return an incomplete comic (without most metadata)

    :param `path`: A folder containing images
    :param `donor_comic`: A comic to fill unfilled metadata from
    :returns A `BaseComic` with metadata and chapter data of that folder
    """
    path = Path(path)

    title = path.stem
    authors: list[str] = []
    url = ""
    genres: list[str] = []
    description = ""
    cover_art = ""
    metadata = BaseMetadata(title, authors, url, genres, description, cover_art)

    chapters = [
        BaseChapter(inode.stem, "", inode.stem)
        for inode in natsorted(path.iterdir(), key=lambda i: i.stem)
        if inode.is_dir()
    ]

    if donor_comic:
        metadata = donor_comic.metadata
        for local, remote in zip(chapters, donor_comic.chapters):
            local.title = remote.title
            local.url = remote.url

    return BaseComic(metadata, chapters)


def save_comic(comic: BaseComic, path: Path | str) -> None:
    """
    Save an `md-metadata.json` from `comic` into `path`.

    :param `comic`: A comic to save
    :param `path`: A folder to save `md-metadata.json` into
    """
    path = Path(path)
    path.mkdir(exist_ok=True)

    json_path = path / MD_METADATA_FILE

    with open(json_path, "w", encoding="utf-8") as file:
        json.dump(comic.asdict(), file)


def discover_local_images(path: Path | str) -> dict[str, list[Path]]:
    """
    Given a comic path, return a dictionary of slugs: images.
    Basically a slightly modified version of os.walk.

    :param `path`: A folder containing images
    :returns A dictionary of {slugs: images}
    """
    path = Path(path)

    return {
        chap.stem: list(sorted(chap.iterdir()))
        for chap in sorted(path.iterdir())  # iterdir does not guarantee any order
        if chap.is_dir()  # force explosion for readability
    }
