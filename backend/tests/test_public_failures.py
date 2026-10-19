import httpx
from backend.services.public_failures import public_failure, retry_after


def test_only_transient_failures_retry_and_rate_limit_keeps_wait():
    def error(status, headers=None):
        return httpx.HTTPStatusError('error', request=httpx.Request('GET','https://example.test'),
                                    response=httpx.Response(status, headers=headers))
    assert public_failure(error(403)) == ('access_restricted', False, None)
    assert public_failure(error(404)) == ('deleted', False, None)
    assert public_failure(error(429, {'Retry-After':'120'})) == ('rate_limited', True, 120)
    assert public_failure(error(503))[1] is True
    assert public_failure(ValueError())[1] is False
    assert retry_after('not a date') is None
