import re


html_re = re.compile(r"<[^>]+?>")

def strip_html(s: str) -> str:
    return html_re.sub("", s)


ruby_re = re.compile(r"(?P<s>\s?)(?P<text>\w+)(?P<ruby>\[[^\]]+?\])")

def strip_ruby(s: str) -> str:
    return ruby_re.sub(r"\g<text>", s)


parenthetical_re = re.compile(r"\s*\([^\)]*\)")

def strip_parenthetical(s: str) -> str:
    return parenthetical_re.sub("", s)


# https://www.mtu.edu/umc/services/websites/writing/characters-avoid/
illegal_characters = "#%&{}\\&<>*?/ $!'\":@+`|="
table = {c: "_" for c in illegal_characters}

def to_filename(s: str) -> str:
    return s.translate(table)