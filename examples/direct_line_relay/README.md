# Direct Line-compatible notification relay

This example runs a local command-line relay for FDAI A2 operational alerts and A4 digests. Use it
to validate the Direct Line-compatible activity and signed publication-receipt contracts without
provisioning a Bot Framework or Terraform environment.

> **Scope:** This relay is a loopback-only validation tool. It is not a production channel, an A1
> approval surface, or an A3 conversation adapter.

## What the example verifies

The relay accepts the same bounded, read-only activity that the FDAI Direct Line adapter sends. It
persists the activity idempotency key before acknowledging the request, returns a stable activity
identifier, and then posts a signed publication receipt to the Operator Service.

A repeated activity returns the same identifier and doesn't publish another receipt. The relay
never accepts attachments, suggested actions, commands, or an unsupported trust tier.

## Run the relay

Provide secrets through environment variables so they don't enter shell history:

```bash
export FDAI_EXAMPLE_DIRECT_LINE_SECRET='<local-relay-secret>'
export FDAI_NOTIFICATION_RECEIPT_SECRET='<local-receipt-secret>'

python3 examples/direct_line_relay/direct_line_relay.py \
  --receipt-url http://127.0.0.1:8000/runtime/integrations/notifications/delivery-receipt \
  --state-file .fdai/direct-line-relay-state.json
```

The command prints bounded JSON events. It doesn't print either secret, the notification body, or
an endpoint credential.

For a one-message check, add `--once`. The relay exits after it submits the publication receipt.

## Bind FDAI locally

Use an explicit `direct_line` binding in `FDAI_NOTIFICATION_BINDINGS_JSON`. Set the endpoint,
conversation, and secret through protected environment references. Production composition
continues to require HTTPS. The focused integration test enables HTTP only for an explicitly
constructed loopback adapter, and that development switch isn't available through runtime binding
configuration.

## Validate

Run the focused end-to-end check:

```bash
uv run pytest -q --no-cov tests/integration/notifications/test_direct_line_relay.py
```

The check uses real loopback HTTP in both directions:

1. The FDAI adapter writes a durable `sending` record and posts the activity to the relay.
2. The relay returns provider acceptance and submits an HMAC-signed publication receipt.
3. The Operator ingress authenticates and publishes the receipt.
4. Core applies `accepted -> delivered`.
5. Replay returns the existing terminal delivery without another relay request.
