"""Give every WebSocket connection its own thread for sync work.

Channels runs `database_sync_to_async` calls as thread-sensitive. Outside a ThreadSensitiveContext, that means one shared
thread per process, so a slow sync call on one socket (a workshop turn that grades an answer with the AI) stalls the
database work of every other socket in that worker. The 500-user load test showed it as 20-60 s tails on AI replies
while HTTP stayed fast. Django already gives each HTTP request its own context; this does the same per connection, so
calls on one socket stay in order and different sockets run in parallel."""

from asgiref.sync import ThreadSensitiveContext


class PerConnectionThreads:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async with ThreadSensitiveContext():
            return await self.app(scope, receive, send)
