# Parser Module

`proxycli.parser` converts proxy URI strings into sing-box outbound
dictionaries. Every public parser returns a `dict` or raises `ValueError` with a
message that identifies the invalid field or unsupported scheme.

## Common Behavior

- URI fragments become sing-box `tag` values.
- Percent-encoded fields are decoded.
- Missing base64 padding is tolerated.
- Ports are validated as integers between 1 and 65535.
- `parse_subscription_content(text)` splits on newlines, skips blanks and
  comment lines, and logs invalid entries without failing the entire batch.

## vmess

Format:

```text
vmess://base64(json)
```

Required JSON fields are server (`add`), port (`port`), UUID (`id`), and
optional display name (`ps`). The parser maps `net`, `path`, and `host` into a
sing-box transport when present.

## Shadowsocks

Legacy format:

```text
ss://base64(method:password@server:port)#name
```

SIP002 format:

```text
ss://base64(method:password)@server:port#name
```

The parser accepts both and emits `type: shadowsocks`, `method`, `password`,
`server`, and `server_port`.

## Trojan

Format:

```text
trojan://password@server:port?security=tls&sni=example.com#name
```

TLS is enabled for `security=tls` and SNI is mapped to
`tls.server_name`.

## VLESS

Format:

```text
vless://uuid@server:port?encryption=none&security=tls&sni=example.com&type=ws&path=/ws#name
```

The parser emits `flow` with an empty string when omitted. Query parameters
create TLS and WebSocket transport blocks when present.

## Hysteria2

Formats:

```text
hysteria2://password@server:port?sni=example.com&insecure=0#name
hy2://password@server:port?sni=example.com#name
```

Both schemes map to sing-box `type: hysteria2`.

## TUIC

Format:

```text
tuic://uuid:password@server:port?sni=example.com&congestion_control=bbr#name
```

The parser maps userinfo to `uuid` and `password`, and includes
`congestion_control` when provided.

## Edge Cases

The parser rejects empty URIs, unsupported schemes, invalid ports, missing
required fields, invalid vmess JSON, and malformed shadowsocks userinfo.
