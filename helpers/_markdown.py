"""Markdown rendering and video embed helpers."""

import re
from html import escape

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
_CUSTOM_VIDEO_RE = re.compile(
    r'<p>\s*\[\[video\s+url="([^"]+)"(?:\s+width="(\d{2,4})")?(?:\s+align="(none|left|right|center)")?(?:\s+ratio="(16:9|4:3|1:1)")?\s*\]\]\s*</p>',
    re.IGNORECASE,
)
_VIDEO_WIDTH_RE = re.compile(r"^\d{2,4}$")
_VIDEO_PADDING_BY_RATIO = {
    "16:9": "56.25%",
    "4:3": "75%",
    "1:1": "100%",
}


def _get_video_embed_src(url):
    """Return the canonical embed URL for a supported video URL, or None."""
    if not url:
        return None
    yt_watch = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", url, re.IGNORECASE)
    if yt_watch:
        return f"https://www.youtube.com/embed/{yt_watch.group(1)}"
    yt_short = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", url, re.IGNORECASE)
    if yt_short:
        return f"https://www.youtube.com/embed/{yt_short.group(1)}"
    vimeo = re.search(r"vimeo\.com/(\d+)", url, re.IGNORECASE)
    if vimeo:
        return f"https://player.vimeo.com/video/{vimeo.group(1)}"
    return None


def _normalize_video_options(width=None, align=None, ratio=None):
    """Return sanitised video sizing options."""
    width = str(width).strip() if width is not None else ""
    if not _VIDEO_WIDTH_RE.match(width):
        width = ""
    align = (align or "center").strip().lower()
    if align not in {"none", "left", "right", "center"}:
        align = "center"
    ratio = (ratio or "16:9").strip()
    if ratio not in _VIDEO_PADDING_BY_RATIO:
        ratio = "16:9"
    return width, align, ratio


def _make_video_iframe(embed_src, source_url=None, width=None, align="center", ratio="16:9"):
    """Return a responsive iframe HTML string for the given embed URL."""
    width, align, ratio = _normalize_video_options(width=width, align=align, ratio=ratio)
    classes = ["video-embed", f"video-embed-{align}"]
    styles = [
        "position:relative",
        f"padding-bottom:{_VIDEO_PADDING_BY_RATIO[ratio]}",
        "height:0",
        "overflow:hidden",
        "max-width:100%",
    ]
    if width:
        styles.append(f"width:min({width}px,100%)")
    elif align == "none":
        styles.append("width:100%")
    if align == "center":
        styles.append("margin:1rem auto")
    elif align == "left":
        styles.append("float:left")
        styles.append("clear:left")
        styles.append("margin:0 1.5rem 1rem 0")
    elif align == "right":
        styles.append("float:right")
        styles.append("clear:right")
        styles.append("margin:0 0 1rem 1.5rem")
    else:
        styles.append("margin:1rem 0")
    attrs = [
        f'class="{" ".join(classes)}"',
        f'data-bw-source-url="{escape(source_url or embed_src, quote=True)}"',
        f'data-bw-align="{align}"',
        f'data-bw-ratio="{ratio}"',
        f'style="{";".join(styles)}"',
    ]
    if width:
        attrs.append(f'data-bw-width="{width}"')
    return (
        f'<div {" ".join(attrs)}>'
        f'<iframe src="{escape(embed_src, quote=True)}" style="position:absolute;top:0;left:0;width:100%;height:100%;border:0" '
        'allowfullscreen loading="lazy"></iframe>'
        '</div>'
    )


def _embed_videos_in_html(html):
    """Replace bare YouTube/Vimeo anchor links with responsive iframe embeds."""
    def _yt_watch_replace(m):
        """Replace a YouTube watch-URL match with an iframe embed."""
        source_url = m.group(1)
        embed_src = _get_video_embed_src(source_url)
        if not embed_src:
            return m.group(0)
        return _make_video_iframe(embed_src, source_url=source_url)

    def _yt_short_replace(m):
        """Replace a youtu.be short-URL match with an iframe embed."""
        source_url = m.group(1)
        embed_src = _get_video_embed_src(source_url)
        if not embed_src:
            return m.group(0)
        return _make_video_iframe(embed_src, source_url=source_url)

    def _vimeo_replace(m):
        """Replace a Vimeo URL match with an iframe embed."""
        source_url = m.group(1)
        embed_src = _get_video_embed_src(source_url)
        if not embed_src:
            return m.group(0)
        return _make_video_iframe(embed_src, source_url=source_url)

    def _custom_video_replace(m):
        """Replace a persisted video shortcode with a configurable iframe embed."""
        source_url = m.group(1)
        embed_src = _get_video_embed_src(source_url)
        if not embed_src:
            return m.group(0)
        return _make_video_iframe(
            embed_src,
            source_url=source_url,
            width=m.group(2),
            align=m.group(3) or "center",
            ratio=m.group(4) or "16:9",
        )

    html = _CUSTOM_VIDEO_RE.sub(_custom_video_replace, html)
    # Handle linked URLs (markdown angle-bracket or explicit link syntax)
    html = _YT_WATCH_RE.sub(_yt_watch_replace, html)
    html = _YT_SHORT_RE.sub(_yt_short_replace, html)
    html = _VIMEO_RE.sub(_vimeo_replace, html)
    # Handle bare URLs (plain text in <p> tags, no markdown linking)
    html = _YT_WATCH_BARE_RE.sub(_yt_watch_replace, html)
    html = _YT_SHORT_BARE_RE.sub(_yt_short_replace, html)
    html = _VIMEO_BARE_RE.sub(_vimeo_replace, html)
    return html
