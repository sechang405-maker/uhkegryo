"""Bounded history contract; no database or external I/O."""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from backend.services.job_repository import JobRepository, JobNotFound

class Pool:
    def __init__(self, pages, cursor=None): self.pages=list(pages); self.calls=[]; self.cursor=cursor
    async def fetch(self, sql, *args): self.calls.append((sql,args)); return self.pages.pop(0)
    async def fetchrow(self, sql, *args): self.calls.append((sql,args)); return self.cursor

def row(i): return {'job_id':str(i),'request_text':str(i),'created_at':i}
def envelope(r): return SimpleNamespace(model_dump=lambda **kw:{'job_id':r['job_id']})

def test_latest_history_bounds_reverses_and_keeps_cursor_on_page():
    async def run():
        pool=Pool([[row(i) for i in range(21,0,-1)],[row(0)],[row(-1)]])
        with patch('backend.services.job_repository._to_envelope',envelope):
            page=await JobRepository(pool).history_page('session',20)
        assert [x['job_id'] for x in page['items']]==[str(i) for i in range(2,22)]
        assert page['has_more'] is True
        assert page['next_before_job_id']=='2'
        assert page['pending_items'][0]['job_id']=='0'
        assert page['reference_item']['job_id']=='-1'
        assert pool.calls[0][1]==('session',21)
        assert 'DESC' in pool.calls[0][0]
    asyncio.run(run())

def test_cursor_resolved_inside_session_and_missing_cursor_rejected():
    async def run():
        pool=Pool([],None)
        with pytest.raises(JobNotFound): await JobRepository(pool).history_page('owned',20,'foreign')
        assert pool.calls[0][1]==('owned','foreign')
        assert 'session_id=$1' in pool.calls[0][0]
    asyncio.run(run())

def test_keyset_uses_created_at_and_id_not_offset():
    async def run():
        pool=Pool([[],[],[]],{'created_at':7,'job_id':'cursor'})
        page=await JobRepository(pool).history_page('owned',20,'cursor')
        assert page['items']==[] and not page['has_more']
        sql,args=pool.calls[1]
        assert '(j.created_at,j.job_id) <' in sql
        assert args==('owned',21,7,'cursor')
    asyncio.run(run())

def test_latest_route_checks_ownership_before_cursor(monkeypatch):
    from backend.routes import agent
    import uuid
    async def run():
        calls=[]
        class Sessions:
            async def get_session(self,token,sid): calls.append(('owned',sid)); raise JobNotFound
        class Jobs:
            async def history_page(self,*args): raise AssertionError('foreign session history queried')
        async def repos(): return Sessions(),Jobs()
        async def owner(*args): return 'owner'
        monkeypatch.setattr(agent,'get_repositories',repos)
        monkeypatch.setattr(agent,'_owner',owner)
        with pytest.raises(agent.ApiContractError):
            await agent.conversation_history(uuid.uuid4(),None,None,20,0,True,uuid.uuid4())
        assert len(calls)==1
    asyncio.run(run())

def test_default_route_retains_ascending_offset_contract(monkeypatch):
    from backend.routes import agent
    import uuid
    async def run():
        calls=[]
        class Sessions:
            async def get_session(self,*args): return {}
        class Jobs:
            async def history(self,*args): calls.append(args); return ['legacy']
        async def repos(): return Sessions(),Jobs()
        async def owner(*args): return 'owner'
        monkeypatch.setattr(agent,'get_repositories',repos)
        monkeypatch.setattr(agent,'_owner',owner)
        sid=uuid.uuid4()
        assert await agent.conversation_history(sid,None,None,20,5,False,None)=={'items':['legacy']}
        assert calls==[(str(sid),20,5)]
    asyncio.run(run())
