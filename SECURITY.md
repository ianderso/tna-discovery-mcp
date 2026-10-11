# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately, through GitHub's
[private vulnerability reporting](https://github.com/ianderso/tna-discovery-mcp/security/advisories/new)
(the **Report a vulnerability** button on the repository's Security tab), not
in a public issue. Include what an attacker controls, what they gain, and the
steps to reproduce it.

You should hear back within a week. Fixes are released for the latest version
only.

## Scope

In scope: this server — the requests it makes, the one file it writes (the
day's call count), and anything a tool argument or an API answer can make it
do.

Out of scope: Discovery itself, which this project does not operate. Report
problems with it to The National Archives.

## The security model, briefly

- **No credentials.** Discovery's API needs none. The server holds no key and
  sends none.
- **Tool arguments are treated as the attacker's.** A model writes them, and
  the model reads catalogue text and web pages that may carry injected
  instructions. Everything below is about what such an argument can make the
  server do.
- **One host.** Every request goes to `https://discovery.nationalarchives.gov.uk/API/`.
  A request hook refuses any other host or scheme, so no argument and no
  answer can point the client elsewhere.
- **Public addresses only, checked at connect time.** The transport resolves
  the host itself, refuses the connection if any address is private,
  loopback, link-local, shared (CGNAT), multicast, reserved, unspecified or
  site-local, in IPv4 or IPv6 (an IPv4-mapped, 6to4 or NAT64 address is judged
  by the IPv4 address inside it), and connects to the address it checked. A
  redirect or a retry is a new connection, checked again, so DNS rebinding
  gains nothing. Proxy settings in the environment are not used: through a
  proxy, the proxy would choose the address.
- **Redirects are followed by hand,** and only on the one host. A redirect
  anywhere else is reported to the caller and not followed.
- **Bounded answers.** An answer over 10 MB is refused as it streams in,
  whether or not its size was declared.
- **Read-only calls.** The client calls five read routes (search, details,
  context, collection by reference, children). The API has no write routes.
- **Arguments are narrowed** before they are placed in a request: ids,
  series and department codes against narrow patterns; dates to full ISO
  dates; a reference percent-encoded as a single path segment, so no slash,
  `?` or `#` in it can change the path; search words only as query
  parameters; a paging cursor printable and short.
- **Local writes.** One file, `budget.json` in `TNA_DISCOVERY_STATE_DIR`,
  holding the day and a count, written atomically. Nothing the API returns is
  written anywhere.
- **API answers carry untrusted text.** Descriptions are written by
  archivists and volunteers and reach the model verbatim, which makes them a
  channel for prompt injection. The server's instructions tell the model to
  treat that text as material, not as instructions, but the model still
  decides what to do next. An injection that leads the model to misuse this
  server's own tools is in scope; one that leads it to misuse other tools the
  client has connected is a client concern.
- **`TNA_DISCOVERY_CONTACT` is checked** for newlines and parentheses before it
  is placed in the User-Agent header.
