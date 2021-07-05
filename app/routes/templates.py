"""
Template engine enhancements
"""
import re

from markupsafe import Markup
from jinja2 import evalcontextfilter, escape
import json

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

@app.template_filter(name="swaplistitem")
def swaplistitem(value, item):
    if isinstance(value, str):
        value = json.loads(value)
        if not isinstance(value, list):
            value = [value]
    if item in value:
        value = list(set(value) - set([item]))
    else:
        value = value + [item]
    return value

@app.template_filter(name="addlistitem")
def addlistitem(value, item):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except:
            pass
        if not isinstance(value, list):
            value = [value]
    if value is None:
        return [item]

    if item not in value:
        value = value + [item]
    return value

@app.template_filter(name="list_to_str")
@evalcontextfilter
def list_to_str(eval_ctx, value):
    if isinstance(value, list):
        return ",".join(map(str, value))
    return value


@app.template_filter(name="json_dump")
@evalcontextfilter
def json_dump(eval_ctx, value):
    return json.dumps(value)

@app.template_filter(name="json_load")
@evalcontextfilter
def json_load(eval_ctx, value):
    try:
        return json.loads(value)
    except:
        return value

@app.template_filter(name="typename")
@evalcontextfilter
def json_load(eval_ctx, value):
    return type(value)


