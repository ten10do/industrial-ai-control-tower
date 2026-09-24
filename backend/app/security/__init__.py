"""Phase 6.12 security and governance foundation.

The package owns identity (``users``), authorization (``roles`` /
``permissions``), the authentication boundary (JWT access tokens and bcrypt
password hashes), and the request-scoped security context that enriches the
existing audit trail with the authenticated actor.

It deliberately stops at a *foundation*. There is no SSO, no OAuth provider, no
token introspection service, no refresh-token rotation, and no policy engine.
Every piece here is small enough to be read end to end and tested
exhaustively, which is the point: an identity layer nobody understands is worse
than no identity layer at all.
"""
