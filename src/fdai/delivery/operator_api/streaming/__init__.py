"""Server-Sent Events (SSE) streaming endpoints for the read-only ASGI (G-5).

SSE fan-out modules live here so the routes/ directory stays HTTP-only
and the streaming lifecycle (long-lived request, StagePublisher hookup,
back-pressure) is grouped in one place.

- :mod:`.live_stream` - the operator-console live event stream.
- :mod:`.live_control_loop` - control-loop stage-by-stage progress fan-out.
- :mod:`.provision_stream` - deployment/provisioning progress SSE.
"""
