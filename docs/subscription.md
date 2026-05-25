# Subscription Module

`proxycli.subscription` is responsible for turning a subscription endpoint into
a generated sing-box config.

## Fetch Flow

`fetch_subscription(url)` uses `httpx.Client` with redirects and a 15 second
timeout. It retries three times with a short linear backoff before raising a
`RuntimeError`.

`update_from_url(url, output_path)` performs the full workflow:

1. Fetch raw text.
2. Decode the body if it looks like a base64-encoded subscription.
3. Parse nodes with `parse_subscription_content`.
4. Reject an update with zero supported nodes.
5. Generate config.
6. Store `subscription_url` and `last_fetch_at` in `state.json`.

## Base64 Handling

Many subscription providers return a base64-encoded newline-separated list of
node URIs. Padding is frequently omitted, so the decoder adds missing padding
before decoding. If the body already contains URI schemes, it is treated as
plain text.

If base64 decoding fails, the text is passed through unchanged. This makes local
or custom plain-text subscriptions work naturally.

## Caching

The module persists metadata, not subscription content. `state.json` stores:

- `subscription_url`: the most recent URL used by `sub update`.
- `last_fetch_at`: Unix timestamp for the most recent successful config update.

The CLI can call `proxycli sub update` without a URL after the first successful
update because the URL is read from state.

## Error Handling

Network failures are retried and then raised. Empty parsed node sets fail the
update to avoid replacing a working config with a selector that has no proxies.

## Partial Failures

Individual invalid node lines are handled in `proxycli.parser`: the parser logs
a warning and skips the failing line. This allows one malformed provider entry
to fail partially while valid nodes still enter the generated config.
