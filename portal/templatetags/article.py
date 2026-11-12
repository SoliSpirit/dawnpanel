import re
from django import template
from django.utils.html import format_html, format_html_join

register=template.Library()
INLINE=re.compile(r'\*\*([^*\n]+)\*\*|\[([^\]\n]+)\]\((https?://[^\s)]+)\)')

def inline(text):
    parts=[]
    pos=0
    for token in INLINE.finditer(text):
        parts.append(text[pos:token.start()])
        parts.append(format_html('<strong>{}</strong>',token[1]) if token[1] else
                     format_html('<a href="{}" rel="noopener noreferrer">{}</a>',token[3],token[2]))
        pos=token.end()
    parts.append(text[pos:])
    return format_html_join('', '{}', ((part,) for part in parts))

@register.filter
def article_body(text):
    blocks=[]
    for block in re.split(r'\n\s*\n',text.replace('\r\n','\n').strip()):
        if not block:continue
        for line in block.splitlines():
            if line.startswith('## '):blocks.append(format_html('<h2>{}</h2>',inline(line[3:])))
            elif line.startswith('### '):blocks.append(format_html('<h3>{}</h3>',inline(line[4:])))
            else:blocks.append(format_html('<p>{}</p>',inline(line)))
    return format_html_join('\n','{}',((block,) for block in blocks))
