import asyncio
import httpx
from backend.schemas.enums import Role, PinStatus
from backend.services.pinterest_widget import PinterestWidgetClient, PinterestWidgetProvider
from backend.services.searxng_pinterest_search import SearXNGPinterestSearchProvider


def run_case(failed=(), count=24, duplicates=False, restriction=None):
    async def run():
        searches, widgets = [], []
        async def search(url, params):
            searches.append(params)
            pins=[{'url':f'https://www.pinterest.com/pin/{i}/'} for i in range(1,count+1)]
            return {'results': pins[:2]+pins if duplicates else pins}
        async def widget(url):
            pin_id=url.rsplit('=',1)[-1]; widgets.append(pin_id)
            if restriction and pin_id=='1':
                raise httpx.HTTPStatusError('limited',request=httpx.Request('GET',url),response=httpx.Response(restriction,headers={'Retry-After':'120'}))
            if pin_id in set(map(str,failed)):
                return {'data':[]}
            return {'data':[{'id':pin_id,'images':{'large':{'url':f'https://i.pinimg.com/{pin_id}.jpg','width':100,'height':200}}}]}
        source=SearXNGPinterestSearchProvider(base_url='http://search',json_loader=search,candidate_limit=24)
        client=PinterestWidgetClient(json_loader=widget)
        result=await PinterestWidgetProvider(source,client).search(Role.BODY,('drawing',))
        await client.aclose()
        return result,searches,widgets
    return asyncio.run(run())


def test_partial_failure_fills_eight_from_one_search_and_next_candidates():
    result,searches,widgets=run_case(failed=(1,2,3))
    assert [pin.pin_id for pin in result.pins]==list(map(str,range(4,12)))
    assert len(searches)==1 and len(widgets)==11
    assert all(pin.status is PinStatus.AVAILABLE for pin in result.pins)


def test_normal_search_stops_after_eight_without_extra_widget_requests():
    result,searches,widgets=run_case()
    assert len(result.pins)==8 and len(widgets)==8 and len(searches)==1


def test_shortage_duplicates_and_total_failure_remain_bounded():
    result,_,widgets=run_case(count=5,failed=(1,2),duplicates=True)
    assert [pin.pin_id for pin in result.pins]==['3','4','5']
    assert len(widgets)==5
    result,_,widgets=run_case(failed=range(1,40),count=40)
    assert result.pins==[] and len(widgets)==24
    assert result.code.value=='PIN_SEARCH_UNAVAILABLE'


def test_restriction_or_rate_limit_stops_further_candidates():
    for status in (403,429):
        result,_,widgets=run_case(restriction=status)
        assert len(widgets)<=8 and len(result.pins)==7
        assert result.search_failure==('rate_limited' if status==429 else 'access_restricted')


def test_empty_widget_response_is_unknown_availability_not_verified_deletion():
    async def run():
        from backend.schemas.models import PinResult
        async def loader(url): return {'data':[]}
        client=PinterestWidgetClient(json_loader=loader)
        result=await client._lookup(PinResult(pin_id='1',pin_url='https://www.pinterest.com/pin/1/',status='available'))
        assert result.status is PinStatus.UNAVAILABLE
        assert result.failure_reason=='unavailable'
        await client.aclose()
    asyncio.run(run())


def test_fill_deduplicates_images_and_preserves_order_without_mutating_candidates():
    async def run():
        from backend.schemas.models import PinResult
        from backend.services.response_assembler import RoleSearchOutcome
        calls = []
        async def loader(url):
            pin_id = url.rsplit('=', 1)[-1]
            calls.append(pin_id)
            image = '1' if pin_id == '2' else pin_id
            return {'data': [{'id': pin_id, 'images': {'large': {
                'url': f'https://i.pinimg.com/{image}.jpg', 'width': 100, 'height': 100}}}]}
        original = RoleSearchOutcome(role=Role.BODY, pins=[PinResult(
            pin_id=str(i), pin_url=f'https://www.pinterest.com/pin/{i}/', status='available')
            for i in [1, 1, *range(2, 25)]])
        client = PinterestWidgetClient(json_loader=loader)
        result = await client.fill_outcome(original)
        assert [pin.pin_id for pin in result.pins] == ['1', *map(str, range(3, 10))]
        assert len(calls) == 9 and len(set(calls)) == 9
        assert all(pin.thumbnail_url is None for pin in original.pins)
        await client.aclose()
    asyncio.run(run())


def test_widget_404_is_unavailable_and_short_rate_limit_does_not_retry():
    async def run(status):
        from backend.schemas.models import PinResult
        calls = []
        async def loader(url):
            calls.append(url)
            raise httpx.HTTPStatusError('upstream', request=httpx.Request('GET', url),
                response=httpx.Response(status, headers={'Retry-After': '1'}))
        client = PinterestWidgetClient(json_loader=loader)
        result = await client._lookup(PinResult(pin_id='1', pin_url='https://www.pinterest.com/pin/1/', status='available'))
        assert result.status is PinStatus.UNAVAILABLE
        assert result.failure_reason == ('rate_limited' if status == 429 else 'unavailable')
        assert len(calls) == 1
        if status == 429:
            assert result.retry_after_seconds == 1
        await client.aclose()
    for status in (404, 429):
        asyncio.run(run(status))


def test_fill_deadline_keeps_completed_healthy_batches():
    async def run():
        from backend.schemas.models import PinResult
        from backend.services.response_assembler import RoleSearchOutcome
        async def loader(url):
            pin_id = url.rsplit('=', 1)[-1]
            if pin_id == '9':
                await asyncio.Event().wait()
            if pin_id == '1':
                return {'data': []}
            return {'data': [{'id': pin_id, 'images': {'large': {
                'url': f'https://i.pinimg.com/{pin_id}.jpg', 'width': 100, 'height': 100}}}]}
        client = PinterestWidgetClient(json_loader=loader)
        result = await client.fill_outcome(RoleSearchOutcome(role=Role.BODY, pins=[PinResult(
            pin_id=str(i), pin_url=f'https://www.pinterest.com/pin/{i}/', status='available')
            for i in range(1, 25)]), timeout_seconds=.05)
        assert [pin.pin_id for pin in result.pins] == list(map(str, range(2, 9)))
        assert result.search_failure == 'temporary'
        await client.aclose()
    asyncio.run(run())


def test_restricted_source_does_not_start_widget_requests():
    async def run():
        from backend.schemas.models import PinResult
        from backend.services.response_assembler import RoleSearchOutcome
        calls = []
        async def loader(url):
            calls.append(url)
            raise AssertionError('restricted searches must not start another upstream lookup')
        client = PinterestWidgetClient(json_loader=loader)
        result = await client.fill_outcome(RoleSearchOutcome(role=Role.BODY,
            search_failure='rate_limited', retry_after_seconds=120,
            pins=[PinResult(pin_id='1', pin_url='https://www.pinterest.com/pin/1/', status='available')]))
        assert not result.pins
        assert result.search_failure == 'rate_limited' and result.retry_after_seconds == 120
        assert calls == []
        await client.aclose()
    asyncio.run(run())


def test_deadline_preserves_completed_pins_within_the_same_batch():
    async def run():
        from backend.schemas.models import PinResult
        from backend.services.response_assembler import RoleSearchOutcome
        async def loader(url):
            pin_id=url.rsplit('=',1)[-1]
            if pin_id=='8': await asyncio.Event().wait()
            return {'data':[{'id':pin_id,'images':{'large':{'url':f'https://i.pinimg.com/{pin_id}.jpg','width':100,'height':200}}}]}
        client=PinterestWidgetClient(json_loader=loader)
        result=await client.fill_outcome(RoleSearchOutcome(role=Role.BODY,pins=[PinResult(
            pin_id=str(i),pin_url=f'https://www.pinterest.com/pin/{i}/',status='available') for i in range(1,9)]),timeout_seconds=.05)
        assert [pin.pin_id for pin in result.pins]==list(map(str,range(1,8)))
        assert result.search_failure=='temporary'
        await client.aclose()
    asyncio.run(run())
