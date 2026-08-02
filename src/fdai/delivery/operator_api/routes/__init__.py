"""HTTP routes for the read-only ASGI (G-5).

Each module here registers one route family (chat, hil callbacks, rule
catalog, ontology graph, panels, promotion gates, reporting, workflow
authoring, Process views, dynamic view assembly, console actions, what-if,
blast radius, bitemporal, LLM cost, measurement summary, pantheon status,
demo findings, rule-fire trace).

The router shape stays plain Starlette ``Route(...)`` lists so
``main.py`` can compose them without a route-registry indirection. When
a new route family lands, it adds one module here plus one entry to the
``main.py`` router list.
"""
