import asyncio
import httpx
from backend.schemas.models import PinResult
from backend.services.pinterest_widget import PinterestWidgetClient


def pin(pin_id):
    return PinResult(pin_id=pin_id,pin_url=f'https://www.pinterest.com/pin/{pin_id}/',status='available')


def test_expired_opaque_preview_and_partial_failure_are_isolated():
    async def run():
        async def loader(url):
            if url.endswith('1'):
                raise httpx.HTTPStatusError('denied',request=httpx.Request('GET',url),response=httpx.Response(403))
            return {'data':[{'id':'2','images':{'x':{'url':'https://i.pinimg.com/a.jpg','width':10,'height':20}}}]}
        client= PinterestWidgetClient(json_loader=loader)
        result=await client._enrich_pins([pin('1'),pin('2'),pin('e1_expired')])
        assert result[0].failure_reason == 'access_restricted'
        assert result[1].thumbnail_url == 'https://i.pinimg.com/a.jpg'
        assert result[2].failure_reason == 'expired'
        assert result[2].status.value == 'unavailable'
        await client.aclose()
    asyncio.run(run())


def test_widget_retry_limit_and_rate_limit_cooldown():
    async def run():
        calls=[]
        async def loader(url):
            calls.append(url)
            raise httpx.HTTPStatusError('limited',request=httpx.Request('GET',url),response=httpx.Response(429,headers={'Retry-After':'120'}))
        client= PinterestWidgetClient(json_loader=loader)
        first=await client._lookup(pin('1'))
        second=await client._lookup(pin('1'))
        assert first.failure_reason == second.failure_reason == 'rate_limited'
        assert first.retry_after_seconds == 120
        assert len(calls)==1
        await client.aclose()
        calls.clear()
        async def timeout(url):
            calls.append(url)
            raise httpx.ReadTimeout('timeout')
        client= PinterestWidgetClient(json_loader=timeout)
        assert (await client._lookup(pin('2'))).failure_reason == 'temporary'
        assert len(calls)==2
        await client.aclose()
    asyncio.run(run())
