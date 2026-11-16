import asyncio
from unittest.mock import AsyncMock

import main


def test_set_commands_sends_menu():
    tg = AsyncMock()
    asyncio.run(main.set_commands(tg))
    tg.set_my_commands.assert_awaited_once()
    names = [item.command for item in tg.set_my_commands.call_args.args[0]]
    assert names == ["start", "help", "settings", "new"]
