import asyncio
import uuid
from types import SimpleNamespace
import httpx
import pytest
from backend.tests.test_conversation_sessions import database_case
from backend.services.session_repository import SessionRepository, SessionBusy
from backend.services.job_repository import JobRepository, JobNotFound, StaleJobAttempt
from backend.shared.auth import SESSION_COOKIE_NAME


def test_local_profile_retains_old_and_new_sessions_and_cleanup_cannot_delete():
    async def case(pool):
        sessions, jobs = SessionRepository(pool), JobRepository(pool)
        old = await sessions.create_session('old-browser')
        await pool.execute("UPDATE sessions SET last_activity_at=now()-interval '5 years'")
        assert await sessions.list_sessions('old-browser') == []
        await sessions.bind_local_profile('local-profile')
        await sessions.bind_local_profile('local-profile')
        rows = await sessions.list_sessions('local-profile')
        assert rows[0]['session_id'] == old and rows[0]['expires_at'] is None
        assert await sessions.resolve_session('old-browser') is None
        # Old cookie/default pointers cannot write into the adopted owner's session.
        old_job,_ = await jobs.submit_new_session(session_token='old-browser',request_text='isolated old browser',idempotency_key=str(uuid.uuid4()))
        assert old_job.session_id != old
        await pool.execute("UPDATE jobs SET status='failed' WHERE job_id=$1",uuid.UUID(old_job.job_id))
        await pool.execute("UPDATE sessions SET last_activity_at=now() WHERE session_id=$1",uuid.UUID(old_job.session_id))
        fresh = await sessions.create_session('local-profile')
        await pool.execute("UPDATE sessions SET last_activity_at=now()-interval '5 years' WHERE retained")
        assert await sessions.delete_expired_sessions() == 0
        assert len(await sessions.list_sessions('local-profile')) == 2
        job, _ = await jobs.submit(session_id=old, request_text='synthetic request', idempotency_key=str(uuid.uuid4()))
        assert (await jobs.claim_next())['job_id'] == uuid.UUID(job.job_id)
        assert await sessions.session_for_job('local-profile',job.job_id) == old
        assert len(await jobs.history(old)) == 1
        assert fresh != old
    asyncio.run(database_case(case))


def test_delete_owner_idempotency_busy_and_no_worker_resurrection():
    async def case(pool):
        sessions, jobs = SessionRepository(pool), JobRepository(pool)
        a, b = await sessions.create_session('a'), await sessions.create_session('b')
        job, _ = await jobs.submit(session_id=a,request_text='synthetic',idempotency_key=str(uuid.uuid4()))
        await sessions.delete_session('b',a)
        assert await sessions.get_session('a',a)
        with pytest.raises(SessionBusy):
            await sessions.delete_session('a',a)
        claimed = await jobs.claim_next()
        with pytest.raises(SessionBusy):
            await sessions.delete_session('a',a)
        await pool.execute("UPDATE jobs SET status='failed' WHERE job_id=$1",uuid.UUID(job.job_id))
        await asyncio.gather(sessions.delete_session('a',a), sessions.delete_session('a',a))
        assert await pool.fetchval('SELECT count(*) FROM jobs WHERE session_id=$1',uuid.UUID(a)) == 0
        assert await sessions.get_session('b',b)
        with pytest.raises(StaleJobAttempt):
            await jobs.extend_lease(job_id=job.job_id,attempt=claimed['attempt'])
        with pytest.raises(JobNotFound):
            await sessions.get_session('a',a)
    asyncio.run(database_case(case))


def test_submit_and_delete_race_is_atomic():
    async def case(pool):
        sessions, jobs = SessionRepository(pool), JobRepository(pool)
        for _ in range(5):
            sid = await sessions.create_session('race-owner')
            outcomes = await asyncio.gather(
                jobs.submit(session_id=sid,request_text='synthetic race',idempotency_key=str(uuid.uuid4())),
                sessions.delete_session('race-owner',sid),return_exceptions=True)
            assert not any(isinstance(x, Exception) and not isinstance(x,(JobNotFound,SessionBusy)) for x in outcomes)
            remaining = await pool.fetchval('SELECT count(*) FROM sessions WHERE session_id=$1',uuid.UUID(sid))
            count = await pool.fetchval('SELECT count(*) FROM jobs WHERE session_id=$1',uuid.UUID(sid))
            assert (remaining,count) in ((0,0),(1,1))
    asyncio.run(database_case(case))


def test_delete_api_auth_csrf_busy_and_error_preserves_records(monkeypatch):
    from backend.main import app
    from backend.routes import agent
    async def case(pool):
        sessions, jobs = SessionRepository(pool), JobRepository(pool)
        async def repositories(): return sessions,jobs
        monkeypatch.setattr(agent,'get_repositories',repositories)
        sid = await sessions.create_session('owner')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            url='/api/sessions/'+sid
            headers={'X-Conversation-Action':'delete'}
            assert (await client.delete(url,headers=headers)).status_code == 401
            client.cookies.set(SESSION_COOKIE_NAME,'owner')
            assert (await client.delete(url)).status_code == 403
            assert (await client.delete(url,headers={**headers,'Origin':'https://evil.invalid'})).status_code == 403
            job,_=await jobs.submit(session_id=sid,request_text='synthetic',idempotency_key=str(uuid.uuid4()))
            assert (await client.delete(url,headers=headers)).status_code == 409
            assert await sessions.get_session('owner',sid)
            await pool.execute("UPDATE jobs SET status='failed' WHERE job_id=$1",uuid.UUID(job.job_id))
            assert (await client.delete(url,headers=headers)).status_code == 204
            assert (await client.delete(url,headers=headers)).status_code == 204
            assert (await client.get(url)).status_code == 404
    asyncio.run(database_case(case))


def test_local_profile_file_is_stable_and_invalid_file_is_not_overwritten(tmp_path):
    from backend.local_profile import load_or_create_profile
    path=tmp_path/'.env.local-profile'
    first=load_or_create_profile(path)
    assert len(first)==43 and load_or_create_profile(path)==first
    path.write_text('invalid-existing-profile')
    with pytest.raises(SystemExit) as error: load_or_create_profile(path)
    assert 'invalid-existing-profile' not in str(error.value)
    assert path.read_text()=='invalid-existing-profile'


def test_local_profile_cookie_recovery_and_nonlocal_rejection(monkeypatch):
    from backend.main import app
    from backend.routes import agent
    settings=SimpleNamespace(llm_backend='codex-cli',local_profile_token='synthetic-profile',
                             allowed_origins='http://127.0.0.1:3100',environment='development')
    monkeypatch.setattr(agent,'get_settings',lambda:settings)
    async def case(pool):
        sessions,jobs=SessionRepository(pool),JobRepository(pool)
        await sessions.create_session('old-browser')
        async def repositories(): return sessions,jobs
        monkeypatch.setattr(agent,'get_repositories',repositories)
        transport=httpx.ASGITransport(app=app,client=('127.0.0.1',9999))
        async with httpx.AsyncClient(transport=transport,base_url='http://127.0.0.1:8000') as client:
            for _ in range(2):
                client.cookies.clear()
                r=await client.post('/api/local/profile',headers={'X-Conversation-Action':'profile'})
                assert r.status_code==200 and r.json()=={'persistent':True}
                assert 'HttpOnly' in r.headers['set-cookie']
                assert len((await client.get('/api/sessions')).json()['items'])==1
            assert (await client.post('/api/local/profile',headers={'X-Conversation-Action':'profile','Origin':'https://evil.invalid'})).status_code==403
    asyncio.run(database_case(case))
