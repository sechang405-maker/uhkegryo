"use client";

import { useCallback, useEffect, useState } from "react";

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: "include", cache: "no-store", ...options });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "요청을 처리하지 못했습니다.");
  return body;
}

export default function AdminDemoPage() {
  const [overview, setOverview] = useState({ accounts: [], invites: [], transfers: [] });
  const [state, setState] = useState("loading");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [issuedCode, setIssuedCode] = useState("");
  const [form, setForm] = useState({ beneficiary_label: "", admin_note: "", initial_limit: 0 });

  const load = useCallback(async () => {
    setState("loading"); setError("");
    try { setOverview(await api("/api/admin/demo")); setState("ready"); }
    catch (cause) { setError(cause.message); setState("error"); }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function mutate(key, path, action, body) {
    if (busy) return;
    setBusy(key); setError("");
    try {
      await api(path, {
        method: path.endsWith("/invites") ? "POST" : path.includes("/transfers/") ? "POST" : path.includes("/revoke") ? "POST" : "PATCH",
        headers: { "content-type": "application/json", "x-admin-action": action },
        body: JSON.stringify(body),
      });
      await load();
    } catch (cause) { setError(cause.message); }
    finally { setBusy(""); }
  }

  async function issue(event) {
    event.preventDefault();
    if (busy) return;
    setBusy("issue"); setError(""); setIssuedCode("");
    try {
      const response = await api("/api/admin/demo/invites", {
        method: "POST",
        headers: { "content-type": "application/json", "x-admin-action": "issue-invite" },
        body: JSON.stringify({ ...form, initial_limit: Number(form.initial_limit) }),
      });
      setIssuedCode(response.raw_code);
      setForm({ beneficiary_label: "", admin_note: "", initial_limit: 0 });
      await load();
    } catch (cause) { setError(cause.message); }
    finally { setBusy(""); }
  }

  function changeLimit(account) {
    const raw = window.prompt("새 누적 총한도를 입력하세요.", String(account.usage.limit));
    if (raw === null) return;
    const next = Number(raw);
    if (!Number.isInteger(next) || next < 0) { setError("한도는 0 이상의 정수여야 합니다."); return; }
    if (!window.confirm(`한도를 변경할까요?\n기존값: ${account.usage.limit}\n새 값: ${next}`)) return;
    mutate(account.account_id, `/api/admin/demo/accounts/${account.account_id}/limit`, "change-limit", {
      new_limit: next, expected_current_limit: account.usage.limit, reason: "관리자 화면에서 한도 변경",
    });
  }

  function changeStatus(account) {
    const next = account.status === "active" ? "disabled" : "active";
    if (!window.confirm(`계정 상태를 변경할까요?\n기존값: ${account.status}\n새 값: ${next}`)) return;
    mutate(account.account_id, `/api/admin/demo/accounts/${account.account_id}/status`, "change-status", {
      status: next, expected_current_status: account.status, reason: "관리자 화면에서 상태 변경",
    });
  }

  function revoke(invite) {
    if (!window.confirm(`${invite.beneficiary_label}의 미사용 초대를 폐기할까요?`)) return;
    mutate(invite.invite_id, `/api/admin/demo/invites/${invite.invite_id}/revoke`, "revoke-invite", {
      reason: "관리자 화면에서 미사용 초대 폐기",
    });
  }

  function decideTransfer(transfer, decision) {
    const action = decision === "approve" ? "approve-transfer" : "reject-transfer";
    const label = decision === "approve" ? "승인" : "거절";
    if (!window.confirm(
      `계정 이전을 ${label}할까요?\n기존: ${transfer.source_email}\n대상: ${transfer.target_email}`
    )) return;
    mutate(
      transfer.transfer_id,
      `/api/admin/demo/transfers/${transfer.transfer_id}/${decision}`,
      action,
      { reason: `관리자 화면에서 계정 이전 ${label}` },
    );
  }

  return <main className="admin-demo-page">
    <header><div><a href="/">← 어케그려</a><h1>초대·사용량 관리</h1></div><button type="button" onClick={load} disabled={state === "loading"}>새로고침</button></header>
    <p>성공한 AI 대화와 새 용어 초안만 1회 차감됩니다. 고정 안내와 이미지 재검색은 차감되지 않습니다.</p>
    {error && <p className="admin-error" role="alert">{error}</p>}
    <section className="admin-card" aria-labelledby="invite-issue-title">
      <h2 id="invite-issue-title">개별 초대 코드 발급</h2>
      <p>코드는 발급 응답에서 한 번만 표시됩니다. 재발급은 기존 미사용 초대를 폐기한 뒤 새 초대를 만들며 한도를 중복 지급하지 않습니다.</p>
      <form onSubmit={issue}>
        <label>관리 이름<input required maxLength={120} value={form.beneficiary_label} onChange={event => setForm({...form, beneficiary_label:event.target.value})} /></label>
        <label>관리자 메모<input maxLength={500} value={form.admin_note} onChange={event => setForm({...form, admin_note:event.target.value})} /></label>
        <label>최초 누적 한도<input type="number" min="0" required value={form.initial_limit} onChange={event => setForm({...form, initial_limit:event.target.value})} /></label>
        <button disabled={Boolean(busy)}>초대 코드 만들기</button>
      </form>
      {issuedCode && <div className="issued-code" role="status"><strong>한 번만 표시되는 초대 코드</strong><code>{issuedCode}</code><button type="button" onClick={() => navigator.clipboard?.writeText(issuedCode)}>복사</button></div>}
    </section>
    <section className="admin-card" aria-labelledby="accounts-title"><h2 id="accounts-title">계정별 누적 사용량</h2>
      {state === "loading" ? <p role="status">불러오는 중…</p> : <div className="admin-table-wrap"><table><thead><tr><th>계정</th><th>상태</th><th>누적 지급</th><th>사용 완료</th><th>처리 중</th><th>이용 가능</th><th>관리</th></tr></thead><tbody>
        {overview.accounts.map(account => <tr key={account.account_id}><td><strong>{account.display_name || account.email_normalized}</strong><small>{account.email_normalized}</small></td><td>{account.status}</td><td>{account.usage.unlimited ? "무제한" : account.usage.limit}</td><td>{account.usage.charged}</td><td>{account.usage.reserved}</td><td>{account.usage.unlimited ? "무제한" : account.usage.remaining}</td><td><button disabled={Boolean(busy)} onClick={() => changeLimit(account)}>한도 변경</button><button disabled={Boolean(busy)} onClick={() => changeStatus(account)}>{account.status === "active" ? "차단" : "차단 해제"}</button></td></tr>)}
      </tbody></table></div>}
    </section>
    <section className="admin-card" aria-labelledby="invites-title"><h2 id="invites-title">초대 내역</h2>
      <ul className="admin-invite-list">{overview.invites.map(invite => <li key={invite.invite_id}><div><strong>{invite.beneficiary_label}</strong><span>{invite.admin_note || "메모 없음"}</span><small>상태 {invite.status} · 코드 끝 {invite.code_hint} · 최초 한도 {invite.initial_ai_request_limit}</small></div>{invite.status === "pending" && <button disabled={Boolean(busy)} onClick={() => revoke(invite)}>미사용 초대 폐기</button>}</li>)}</ul>
    </section>
    <section className="admin-card" aria-labelledby="transfers-title"><h2 id="transfers-title">Google 계정 이전 요청</h2>
      <p>사용자가 새 Google 로그인을 완료해 검증된 요청만 표시됩니다. 승인하면 데이터와 누적 사용량은 유지되고 이전 로그인 세션은 종료됩니다.</p>
      {overview.transfers.length === 0 ? <p>대기 중인 요청이 없습니다.</p> : <ul className="admin-invite-list">{overview.transfers.map(transfer => <li key={transfer.transfer_id}><div><strong>{transfer.source_display_name || transfer.source_email}</strong><span>{transfer.source_email} → {transfer.target_display_name || transfer.target_email} ({transfer.target_email})</span><small>만료 {new Date(transfer.expires_at).toLocaleString()}</small></div><div><button disabled={Boolean(busy)} onClick={() => decideTransfer(transfer, "approve")}>이전 승인</button><button disabled={Boolean(busy)} onClick={() => decideTransfer(transfer, "reject")}>거절</button></div></li>)}</ul>}
    </section>
  </main>;
}
