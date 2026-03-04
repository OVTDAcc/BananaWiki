"""Markdown rendering and video embed helpers."""

import re

import markdown
import bleach

from ._constants import ALLOWED_TAGS, ALLOWED_ATTRS


def render_markdown(text, embed_videos=False):
    """Convert markdown to sanitised HTML.

    When *embed_videos* is True, bare YouTube and Vimeo links are replaced
    with responsive iframe embeds after sanitisation.
    """
    html = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "toc", "nl2br"],
    )
    html = bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS)
    if embed_videos:
        html = _embed_videos_in_html(html)
    return html


_YT_WATCH_RE = re.compile(
    r'<a href="(https?://(?:www\.)?youtube\.com/watch\?[^"<]*)">\1</a>',
    re.IGNORECASE,
)
_YT_SHORT_RE = re.compile(
    r'<a href="(https?://youtu\.be/[^"<]*)">\1</a>',
    re.IGNORECASE,
)
_VIMEO_RE = re.compile(
    r'<a href="(https?://(?:www\.)?vimeo\.com/[^"<]*)">\1</a>',
    re.IGNORECASE,
)

# Bare URL patterns (markdown does not autolink plain URLs; they appear as text)
_YT_WATCH_BARE_RE = re.compile(
    r'<p>\s*(https?://(?:www\.)?youtube\.com/watch\?[^\s<>]*)\s*</p>',
    re.IGNORECASE,
)
_YT_SHORT_BARE_RE = re.compile(
    r'<p>\s*(https?://youtu\.be/[^\s<>]*)\s*</p>',
    re.IGNORECASE,
)
_VIMEO_BARE_RE = re.compile(
    r'<p>\s*(https?://(?:www\.)?vimeo\.com/(\d+)[^\s<>]*)\s*</p>',
    re.IGNORECASE,
)


def _make_video_iframe(embed_src):
    """Return a responsive iframe HTML string for the given embed URL."""
    return (
        '<div class="video-embed" style="position:relative;padding-bottom:56.25%;height:0;overflow:hidden;margin:1rem 0">'
        f'<iframe src="{embed_src}" style="position:absolute;top:0;left:0;width:100%;height:100%;border:0" '
        'allowfullscreen loading="lazy"></iframe>'
        '</div>'
    )


def _embed_videos_in_html(html):
    """Replace bare YouTube/Vimeo anchor links with responsive iframe embeds."""
    _yt_vid_re = re.compile(r'[?&]v=([A-Za-z0-9_-]{11})', re.IGNORECASE)
    _yt_short_re = re.compile(r'youtu\.be/([A-Za-z0-9_-]{11})', re.IGNORECASE)
    _vimeo_vid_re = re.compile(r'vimeo\.com/(\d+)', re.IGNORECASE)

    def _yt_watch_replace(m):
        """Replace a YouTube watch-URL match with an iframe embed."""
        vid_m = _yt_vid_re.search(m.group(1))
        if not vid_m:
            return m.group(0)
        return _make_video_iframe(f"https://www.youtube.com/embed/{vid_m.group(1)}")

    def _yt_short_replace(m):
        """Replace a youtu.be short-URL match with an iframe embed."""
        vid_m = _yt_short_re.search(m.group(1))
        if not vid_m:
            return m.group(0)
        return _make_video_iframe(f"https://www.youtube.com/embed/{vid_m.group(1)}")

    def _vimeo_replace(m):
        """Replace a Vimeo URL match with an iframe embed."""
        vid_m = _vimeo_vid_re.search(m.group(1))
        if not vid_m:
            return m.group(0)
        return _make_video_iframe(f"https://player.vimeo.com/video/{vid_m.group(1)}")

    # Handle linked URLs (markdown angle-bracket or explicit link syntax)
    html = _YT_WATCH_RE.sub(_yt_watch_replace, html)
    html = _YT_SHORT_RE.sub(_yt_short_replace, html)
    html = _VIMEO_RE.sub(_vimeo_replace, html)
    # Handle bare URLs (plain text in <p> tags, no markdown linking)
    html = _YT_WATCH_BARE_RE.sub(_yt_watch_replace, html)
    html = _YT_SHORT_BARE_RE.sub(_yt_short_replace, html)
    html = _VIMEO_BARE_RE.sub(_vimeo_replace, html)
    return html
