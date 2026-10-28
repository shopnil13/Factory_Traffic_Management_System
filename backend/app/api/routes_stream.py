from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.infrastructure.sse import sse_broadcaster

router = APIRouter(prefix="/api", tags=["Stream"])


@router.get("/stream")
async def sse_stream():
    """Server-Sent Events endpoint pushing real-time state and audit events."""
    return StreamingResponse(
        sse_broadcaster.event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
