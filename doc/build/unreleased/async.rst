.. change::
    :tags: feature, template

    Added support for asynchronous rendering.  Templates that use
    ``await``, ``% async for`` or ``% async with`` are compiled with
    async render callables and are rendered with the new
    :meth:`.Template.render_async` and :meth:`.Template.render_async_def`
    methods.  ``<%inherit>``, ``<%include>``, ``<%block>`` and
    ``<%call>`` work across the async boundary, including templates
    loaded through :class:`.TemplateLookup`; expressions such as
    ``${self.body()}`` that resolve to async callables are awaited
    automatically.  Calling the synchronous :meth:`.Template.render`
    on a template that uses async syntax raises
    :class:`.RuntimeException`; templates without async syntax render
    identically through either entry point, and cache keys are
    unchanged.
