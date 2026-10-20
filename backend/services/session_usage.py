"""Session lifetime usage counts accepted jobs, including failed jobs."""
SESSION_MESSAGE_LIMIT = 20
USAGE_COUNT_SQL = "(SELECT count(*) FROM jobs usage_jobs WHERE usage_jobs.session_id=s.session_id) AS message_count"


def session_usage(message_count: int) -> dict:
    return {"message_count": message_count, "message_limit": SESSION_MESSAGE_LIMIT,
            "remaining_messages": max(0, SESSION_MESSAGE_LIMIT - message_count),
            "can_submit": message_count < SESSION_MESSAGE_LIMIT}
