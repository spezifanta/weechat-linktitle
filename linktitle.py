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

'''WeeChat script that automatically fetches link titles for posted URLs.'''

# History:
# 2011-05-24, Bluthund
#   version 0.1: initial version

from __future__ import print_function

try:
    import weechat
except:
    print('This script is supposed to be run in WeeChat.\n'
          'You can get WeeChat at http://weechat.org.\n\n'
          'Error: Failed to import weechat module.')
    weechat = None

import urllib2
import re

SCRIPT_NAME    = 'linktitle'
SCRIPT_AUTHOR  = 'Bluthund <bluthund23@gmail.com>'
SCRIPT_VERSION = '0.1'
SCRIPT_LICENSE = 'GPL3'
SCRIPT_DESC    = 'Show the title of incoming links.'

TIMEOUT = 3 # seconds

# only fetch link titles for http|https schemas
# no need for the full RFC regex (RFC 1034 & 1738); urllib2 takes care of that
linkRegex = re.compile(r'https?://[^ ]+', re.I)

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

def print_link_title(buf, link):
    try:
        req = urllib2.Request(link)
        req.add_header('User-Agent',
                       'WeeChat/{0}'.format(weechat.info_get('version', '')))

        resp = urllib2.urlopen(req, None, TIMEOUT)

        body = ''.join(resp.readlines()).translate(None, '\r\n')

        title = body[body.find('<title>')+7:body.find('</title>')]
        title = re.sub(r'\s+', ' ', title.strip())
        title = unescape(title)

        weechat.prnt(buf, '[linktitle]\t{0}'.format(title.encode('utf-8')))
    except:
        pass # TODO

def link_cb(data, buf, date, tags, displayed, hilight, prefix, message):
    for link in linkRegex.findall(message):
        print_link_title(buf, link)

    return weechat.WEECHAT_RC_OK

if __name__ == '__main__':
    if weechat:
        weechat.register(SCRIPT_NAME, SCRIPT_AUTHOR, SCRIPT_VERSION,
                         SCRIPT_LICENSE, SCRIPT_DESC, '', '')
        weechat.hook_print('', '', '', 1, 'link_cb', '')
