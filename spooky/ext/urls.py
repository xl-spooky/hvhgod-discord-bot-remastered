import re

import aiohttp
from spooky.ext.http import HttpClient

URL_REGEX = re.compile(
    r"(?i)\b((?:https?://|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)"
    r"(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))"
    r"+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:'\".,<>?«»“”']))"
)


def string_has_url(string: str, /) -> bool:
    """Check if the given string contains a URL.

    Converts the string to lowercase and checks for the presence of a "/" as a
    simple indicator. If found, returns True immediately. Otherwise, uses a regular
    expression to search for a URL pattern.

    Args
    ----
        string (str):
            The string to search for URLs.

    Returns
    -------
        bool:
            True if a URL is found in the string, False otherwise.
    """
    lower_string = string.lower()
    if "/" in lower_string:
        return True

    return URL_REGEX.search(string) is not None


async def validate_url(url: str, /, content_type: str = "image") -> bool:
    """Validate a URL by checking its accessibility and content type.

    Sends a GET request to the specified URL and verifies that the response is successful.
    Additionally, checks if the response has a Content-Length and that the specified content type
    is present in the Content-Type header.

    Args
    ----
        url (str):
            The URL to validate.
        content_type (str, optional):
            The expected content type (e.g., "image"). Defaults to "image".

    Returns
    -------
        bool:
            True if the URL is accessible and the response Content-Type includes the specified type,
            False otherwise.
    """
    try:
        async with HttpClient.session.get(url) as response:
            if not response.ok:
                return False

            return response.content_length is not None and content_type in response.headers.get(
                aiohttp.hdrs.CONTENT_TYPE, ""
            )
    except aiohttp.ClientError:
        return False
