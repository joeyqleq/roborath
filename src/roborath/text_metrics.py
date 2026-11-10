"""Message-content counts; metadata labels and username mentions are excluded."""
import re
import unicodedata


def message_content(text,username='',reply_username=''):
    value=str(text)
    for name in (username,reply_username):
        if name:
            # Only remove known leading labels; names in ordinary prose remain
            # content. Twitch metadata username fields never enter this text.
            value=re.sub(r'^\s*@?'+re.escape(name)+r'(?=\s|[:,])\s*[:,]?\s*','',value,count=1,flags=re.I)
    value=re.sub(r'(?<!\w)@[a-z0-9_]{1,25}\b','',value,flags=re.I)
    return ''.join(c for c in value if unicodedata.category(c)!='Cf')


def content_counts(text,username='',reply_username=''):
    value=message_content(text,username,reply_username)
    words=len(re.findall(r"\b[\w’'-]+\b",value,flags=re.UNICODE))
    chars=sum(not c.isspace() for c in value)
    return words,chars
