# billing_webhooks

Payment webhooks are delivered at-least-once. Handlers must use the event_id as an idempotency key, otherwise retries can charge twice.
