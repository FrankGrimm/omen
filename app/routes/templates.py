"""
Template engine enhancements
"""
import re

from markupsafe import Markup
from jinja2 import evalcontextfilter, escape

from app.web import app, BASEURI, db
_paragraph_re = re.compile(r'(?:\r\n|\r(?!\n)|\n){2,}')

@app.template_filter(name="nl2br")
@evalcontextfilter
def nl2br(eval_ctx, value):
    result = u'\n\n'.join(u'<p>%s</p>' % p.replace('\n', Markup('<br>\n')) for p in _paragraph_re.split(escape(value)))
    if eval_ctx.autoescape:
        result = Markup(result)
    return result

@app.template_filter(name="highlight")
def highlight(value, query):
    if query is not None and query.strip() != "":
        query = r"(" + re.escape(query.strip()) + ")"
        value = Markup.escape(value)
        value = re.sub(query, lambda g: '<span class="ds_highlight">%s</span>' % g.group(1),
                       value, flags=re.IGNORECASE)

    return Markup(value)
