# PAYMENT-REQUIRED golden fixtures
Each JSON file stores one unauthenticated HTTP response for the v2 header check.
`name`, `url`, `method`, and `status` identify the captured or synthetic probe.
`headers` contains response headers with lowercased names.
`body` is always the raw response body as a string.
`expect.passed` records whether the payment-required extraction should pass.
`expect.channel` is one of `header`, `body`, `both`, or `none`.
`expect.legacy_placement` marks body-only v1 compatibility cases.
`expect.failure_class` is null unless a specific failure is expected.
Fixtures captured from POST routes may also include `request_body` so their
published Bazaar input contract remains reproducible.
`provenance` may record independently confirmed settlement facts while the
fixture itself remains the non-paying unauthenticated quote.
