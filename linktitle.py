#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim: ts=4 et sw=4

# Copyright (C) 2011  Bluthund <bluthund23@gmail.com>
# Function for unescaping HTML entities by Fredrik Lundh <http://effbot.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""WeeChat script that automatically fetches link titles for posted URLs."""

from __future__ import print_function

try:
    import weechat
except:
    weechat = None

import urllib2
import re
import sys
import HTMLParser

from time import time

SCRIPT_NAME    = "linktitle"
SCRIPT_AUTHOR  = "Bluthund <bluthund23@gmail.com>"
SCRIPT_VERSION = "0.2"
SCRIPT_LICENSE = "GPL3"
SCRIPT_DESC    = "Show the title of incoming links."

SCRIPT_PREFIX = "[linktitle]"

TIMEOUT = 3 # seconds

weechat_encoding = "utf-8" # use utf-8 as fallback

# only fetch link titles for http|https schemas
# no need for the full RFC regex (RFC 3986); urllib2 takes care of the rest
linkRegex = re.compile(r"https?://[^ >]+", re.I)

# url cache: dict<str(url), (int(time.time()), str(title))>
url_cache = {}
# only re-retrieve titles of cached URLs after this lifetime (in s)
CACHE_LIFETIME = 6 * 60 * 60

# Unescape HTML Entities; thanks to Fredrik Lundh
# http://effbot.org/zone/re-sub.htm#unescape-html
import htmlentitydefs

def unescape(text):
    def fixup(m):
        text = m.group(0)
        if text[:2] == "&#":
            # character reference
            try:
                if text[:3] == "&#x":
                    return unichr(int(text[3:-1], 16))
                else:
                    return unichr(int(text[2:-1]))
            except ValueError:
                pass
        else:
            # named entity
            try:
                text = unichr(htmlentitydefs.name2codepoint[text[1:-1]])
            except KeyError:
                pass
        return text # leave as is
    return re.sub("&#?\w+;", fixup, text)

class MetaTagParser(HTMLParser.HTMLParser):
    # see "RFC 2616 - Hypertext Transfer Protocol -- HTTP/1.1"
    # NOTE omitted ASCII control characters
    token_class = r"[^()<>@,;:\\\"/[\]?={} \t]+"

    contenttype_re = "({0}/{0})(?:;\s*charset=({0}))?".format(token_class)

    def __init__(self):
        self.charset = None
        self.contenttype = None
        HTMLParser.HTMLParser.__init__(self)

    def _process_meta_tag(self, tag, attrs):
        def parse_http_equiv(attrs):
            for _, value in attrs:
                m = re.match(self.contenttype_re, value)
                if m:
                    return m.groups()
            return None, None

        if tag != "meta":
            return

        for name, value in attrs:
            if name == "charset":
                self.charset = value
            elif name == "http-equiv" and value == "content-type":
                self.contenttype, self.charset = parse_http_equiv(attrs)

    def handle_starttag(self, tag, attrs):
        self._process_meta_tag(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        self._process_meta_tag(tag, attrs)

def check_meta_info(headers, body):
    contenttype = None

    if "Content-Type: " in headers:
        pattern = "^Content-Type:\s*{0}$".format(MetaTagParser.contenttype_re)
        m = re.search(pattern, headers, re.M)

        if m.group(2): # found both: content-type and charset
            return m.groups()
        else:
            contenttype = m.group(1)

    p = MetaTagParser()
    p.contenttype = contenttype
    try:
        p.feed(body)
        p.close()
    except HTMLParser.HTMLParseError:
        pass
    finally:
        return p.contenttype, p.charset

def print_title_cb(buf, cmd, rc, stdout, stderr):
    if stdout != "":
        print_title_cb.resp += stdout
    if stderr != "":
        print(stderr)

    if rc >= 0 and len(print_title_cb.resp):
        resp = print_title_cb.resp
        print_title_cb.resp = ""

        sep = resp.index("\n\n")
        headers = resp[:sep+1]
        body = resp[sep+2:].translate(None, "\r\n")

        contenttype, charset = check_meta_info(headers, body)

        try:
            body = body.decode(charset);
        except TypeError: # charset was None
            pass
        except LookupError: # couldn't find specified input encoding
            # TODO this is actually really bad
            pass # for now

        if "<title>" in body.lower():
            title = body[body.lower().find("<title>")+7:
                         body.lower().find("</title>")]
        else:
            title = "No Title"
        title = re.sub(r"\s+", " ", title.strip())
        title = unescape(title)

        url_cache[''] = (time(), title) # TODO set key to url

        print_to_buffer(buf, title.encode(weechat_encoding))

    return weechat.WEECHAT_RC_OK
print_title_cb.resp = ""

def print_to_buffer(buf, msg):
    weechat.prnt(buf, "{pre}\t{msg}".format(pre = SCRIPT_PREFIX, msg = msg))


def print_link_title(buf, link):
    if link in url_cache and time() < url_cache[link][0] + CACHE_LIFETIME:
        print_to_buffer(buf, url_cache[link][1])
        return weechat.WEECHAT_RC_OK

    cmd = "{exe} -c 'from __future__ import print_function\n\n"\
          "try:\n"\
          "  import urllib2; req = urllib2.Request(\"{link}\")\n"\
          "  req.add_header(\"User-Agent\", \"WeeChat/{ver}\")\n"\
          "  resp = urllib2.urlopen(req, None, {timeout})\n"\
          "  print(resp.info())\n"\
          "  print(resp.read({readmax}))\n"\
          "except: pass'"
    cmd = cmd.format(exe = sys.executable,
                     link = link,
                     ver = weechat.info_get("version", ""),
                     timeout = TIMEOUT,
                     readmax = 8192)

    weechat.hook_process(cmd, 0, "print_title_cb", buf)

    return weechat.WEECHAT_RC_OK

def link_cb(data, buf, date, tags, displayed, hilight, prefix, message):
    # don't look at own output or output in core buffer
    if prefix == SCRIPT_PREFIX or buf == weechat.buffer_search_main():
        return weechat.WEECHAT_RC_OK

    for link in linkRegex.findall(message):
        print_link_title(buf, link)

    return weechat.WEECHAT_RC_OK

if __name__ == "__main__":
    if weechat:
        weechat.register(SCRIPT_NAME, SCRIPT_AUTHOR, SCRIPT_VERSION,
                         SCRIPT_LICENSE, SCRIPT_DESC, "", "")

        weechat_encoding = weechat.info_get("charset_internal", "")

        weechat.hook_print("", "", "://", 1, "link_cb", "")
    else:
        print("This script is supposed to be run in WeeChat.\n"
              "You can get WeeChat at http://weechat.org.\n\n"
              "Error: Failed to import weechat module.")
