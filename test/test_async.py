import asyncio

import pytest

from mako import exceptions
from mako.cache import CacheImpl
from mako.cache import register_plugin
from mako.lookup import TemplateLookup
from mako.template import Template
from mako.testing.assertions import assert_raises_message
from mako.testing.assertions import eq_


class MockCacheImpl(CacheImpl):
    def __init__(self, cache):
        self.cache = cache
        self.data = {}

    def get_or_create(self, key, creation_function, **kw):
        if key not in self.data:
            self.data[key] = creation_function()
        return self.data[key]

    def set(self, key, value, **kw):
        self.data[key] = value

    def get(self, key, **kw):
        return self.data.get(key, None)

    def invalidate(self, *keys, **kw):
        for key in keys:
            self.data.pop(key, None)


register_plugin("mock_async", __name__, "MockCacheImpl")


def run(coro):
    return asyncio.run(coro)


async def arows(*values):
    for value in values:
        yield value


async def avalue(value):
    return value


class AsyncCM:
    async def __aenter__(self):
        return "cm-value"

    async def __aexit__(self, *args):
        return False


class AsyncRenderTest:
    def test_async_for(self):
        t = Template(
            "Hello ${name}\n"
            "% async for row in fetch():\n"
            "${row}\n"
            "% endfor"
        )
        eq_(
            run(t.render_async(name="x", fetch=lambda: arows("a", "b"))),
            "Hello x\na\nb\n",
        )

    def test_async_for_else(self):
        t = Template(
            "% async for row in fetch():\n"
            "${row}\n"
            "% else:\n"
            "empty\n"
            "% endfor"
        )
        eq_(run(t.render_async(fetch=lambda: arows())), "empty\n")

    def test_async_with(self):
        t = Template("% async with cm() as v:\n[${v}]\n% endwith")
        eq_(run(t.render_async(cm=AsyncCM)), "[cm-value]\n")

    def test_await_expression(self):
        t = Template("V=${await avalue(99)}")
        eq_(run(t.render_async(avalue=avalue)), "V=99")

    def test_await_code_block(self):
        t = Template("<% x = await avalue(41) %>${x + 1}")
        eq_(run(t.render_async(avalue=avalue)), "42")

    def test_sync_template_renders_normally(self):
        t = Template("plain ${v}")
        eq_(run(t.render_async(v=1)), "plain 1")
        eq_(t.render(v=1), "plain 1")

    def test_sync_render_raises(self):
        t = Template("${await avalue(1)}")
        for render in (t.render, t.render_unicode):
            assert_raises_message(
                exceptions.RuntimeException,
                "uses async syntax",
                render,
                avalue=avalue,
            )

    def test_render_context_raises(self):
        import io

        from mako.runtime import Context

        t = Template("${await avalue(1)}")
        context = Context(io.StringIO(), avalue=avalue)
        assert_raises_message(
            exceptions.RuntimeException,
            "uses async syntax",
            t.render_context,
            context,
        )

    def test_enable_async_module_attr(self):
        eq_(getattr(Template("hi ${x}").module, "_enable_async", False), False)
        eq_(Template("${await avalue(1)}").module._enable_async, True)

    def test_render_async_def(self):
        t = Template(
            '<%def name="greet(who)">hi ${who} ${await avalue(7)}</%def>'
        )
        eq_(run(t.render_async_def("greet", "bob", avalue=avalue)), "hi bob 7")
        eq_(
            run(t.get_def("greet").render_async("ann", avalue=avalue)),
            "hi ann 7",
        )

    def test_def_call_from_body(self):
        t = Template(
            '<%def name="inner()">IN${await avalue(9)}</%def>${inner()}'
        )
        eq_(run(t.render_async(avalue=avalue)), "IN9")

    def test_anonymous_block(self):
        t = Template("A<%block>B${await avalue(1)}</%block>Z")
        eq_(run(t.render_async(avalue=avalue)), "AB1Z")

    def test_call_tag(self):
        t = Template(
            '<%def name="wrap()">'
            "<W>${caller.body()}</W>"
            "</%def>"
            '<%call expr="wrap()">body-${await avalue(5)}</%call>'
        )
        eq_(run(t.render_async(avalue=avalue)), "<W>body-5</W>")

    def test_loop_context_still_works(self):
        t = Template(
            "% for i in [1, 2]:\n"
            "${loop.index}:${i}\n"
            "% endfor\n"
            "${await avalue(3)}"
        )
        eq_(run(t.render_async(avalue=avalue)), "0:1\n1:2\n3")

    def test_error_handler(self):
        seen = []

        def handler(context, error):
            seen.append(str(error))
            return True

        async def boom():
            raise ValueError("kaboom")

        t = Template("${await boom()}", error_handler=handler)
        eq_(run(t.render_async(boom=boom)), "")
        eq_(seen, ["kaboom"])

    def test_format_exceptions(self):
        async def boom():
            raise ValueError("kaboom")

        t = Template("${await boom()}", format_exceptions=True)
        assert b"kaboom" in run(t.render_async(boom=boom))

    def test_strict_undefined(self):
        t = Template("${await avalue(1)} ${missing}", strict_undefined=True)
        with pytest.raises(NameError):
            run(t.render_async(avalue=avalue))

    def test_rich_traceback_lineno(self):
        async def boom():
            raise ValueError("kaboom")

        t = Template(
            "line1\n${await boom()}\nline3", filename="/fake/t.html"
        )
        try:
            run(t.render_async(boom=boom))
        except ValueError:
            tb = exceptions.RichTraceback()
        else:
            pytest.fail("expected ValueError")
        eq_(
            [rec[1] for rec in tb.traceback if rec[0] == "/fake/t.html"],
            [2],
        )

    def test_cache_id_unchanged(self):
        # the cache key of a template is derived from its module name;
        # the async entry points must not change it
        t = Template("hello ${x}", cache_impl="mock_async")
        eq_(t.cache.id, t.module.__name__)
        t = Template("${await avalue(1)}", cache_impl="mock_async")
        eq_(t.cache.id, t.module.__name__)

    def test_cached_page(self):
        t = Template(
            '<%page cached="True"/>C-${await avalue(1)}',
            cache_impl="mock_async",
        )
        eq_(run(t.render_async(avalue=avalue)), "C-1")
        eq_(run(t.render_async(avalue=avalue)), "C-1")

    def test_cached_def(self):
        t = Template(
            '<%def name="c()" cached="True">CD${await avalue(2)}</%def>'
            "${c()}",
            cache_impl="mock_async",
        )
        eq_(run(t.render_async(avalue=avalue)), "CD2")
        eq_(run(t.render_async(avalue=avalue)), "CD2")


class AsyncIncludeInheritTest:
    @pytest.fixture
    def lookup(self, tmp_path):
        (tmp_path / "sync_base.html").write_text(
            "BASE-START\n${self.body()}\nBASE-END\n"
        )
        (tmp_path / "async_base.html").write_text(
            "ABASE ${await avalue(1)}\n${self.body()}\n"
        )
        (tmp_path / "async_child.html").write_text(
            '<%inherit file="sync_base.html"/>\n'
            "CHILD ${await avalue(2)}\n"
        )
        (tmp_path / "sync_child.html").write_text(
            '<%inherit file="async_base.html"/>\nSYNC-CHILD\n'
        )
        (tmp_path / "async_inc.html").write_text("AINC ${await avalue(3)}\n")
        (tmp_path / "sync_inc.html").write_text("SINC ${v}\n")
        (tmp_path / "async_includer.html").write_text(
            "P\n"
            '<%include file="async_inc.html"/>\n'
            '<%include file="sync_inc.html" args="v=4"/>\n'
        )
        (tmp_path / "sync_includer.html").write_text(
            "P\n<%include file=\"async_inc.html\"/>\n"
        )
        (tmp_path / "block_base.html").write_text(
            '<%block name="head">BASE-HEAD</%block>\n${self.body()}\n'
        )
        (tmp_path / "block_child.html").write_text(
            '<%inherit file="block_base.html"/>\n'
            '<%block name="head">CHILD-HEAD ${await avalue(5)}</%block>\n'
            "CHILD-BODY\n"
        )
        (tmp_path / "sync_inc_decl.html").write_text(
            '<%page args="v"/>SINC ${v}\n'
        )
        (tmp_path / "async_includer2.html").write_text(
            "P\n"
            '<%include file="async_inc.html"/>\n'
            '<%include file="sync_inc_decl.html" args="v=4"/>\n'
        )
        return TemplateLookup(directories=[str(tmp_path)])

    def test_async_child_sync_base(self, lookup):
        t = lookup.get_template("async_child.html")
        eq_(
            run(t.render_async(avalue=avalue)),
            "BASE-START\n\nCHILD 2\n\nBASE-END\n",
        )

    def test_sync_child_async_base(self, lookup):
        t = lookup.get_template("sync_child.html")
        eq_(
            run(t.render_async(avalue=avalue)),
            "ABASE 1\n\nSYNC-CHILD\n\n",
        )

    def test_sync_render_async_base_raises(self, lookup):
        t = lookup.get_template("sync_child.html")
        assert_raises_message(
            exceptions.RuntimeException,
            "uses async syntax",
            t.render,
            avalue=avalue,
        )

    def test_async_includes(self, lookup):
        t = lookup.get_template("async_includer2.html")
        eq_(
            run(t.render_async(avalue=avalue)),
            "P\nAINC 3\n\nSINC 4\n\n",
        )

    def test_sync_includer_of_async_raises(self, lookup):
        t = lookup.get_template("sync_includer.html")
        assert_raises_message(
            exceptions.RuntimeException,
            "uses async syntax",
            t.render,
            avalue=avalue,
        )

    def test_sync_includer_render_async(self, lookup):
        t = lookup.get_template("sync_includer.html")
        eq_(run(t.render_async(avalue=avalue)), "P\nAINC 3\n\n")

    def test_named_block_override(self, lookup):
        t = lookup.get_template("block_child.html")
        eq_(
            run(t.render_async(avalue=avalue)),
            "CHILD-HEAD 5\n\n\nCHILD-BODY\n\n",
        )

    def test_sync_template_via_lookup(self, lookup):
        t = lookup.get_template("sync_inc.html")
        eq_(run(t.render_async(v=1)), t.render(v=1))
