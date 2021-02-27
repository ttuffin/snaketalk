import asyncio
import json
import logging
import re
from collections import defaultdict
from queue import Empty, Queue
from typing import Dict, Optional, Sequence

from snaketalk.driver import Driver
from snaketalk.plugins import Plugin
from snaketalk.settings import Settings
from snaketalk.wrappers import ActionEvent, Message, WebHookEvent


class EventHandler(object):
    def __init__(
        self,
        driver: Driver,
        settings: Settings,
        plugins: Sequence[Plugin],
        ignore_own_messages=True,
    ):
        """The EventHandler class takes care of the connection to mattermost and calling
        the appropriate response function to each event."""
        self.driver = driver
        self.settings = settings
        self.ignore_own_messages = ignore_own_messages
        self.plugins = plugins

        self._name_matcher = re.compile(rf"^@?{self.driver.username}\:?\s?")

        # Collect the listeners from all plugins
        self.message_listeners = defaultdict(list)
        self.webhook_listeners = defaultdict(list)
        for plugin in self.plugins:
            for matcher, functions in plugin.message_listeners.items():
                self.message_listeners[matcher].extend(functions)
            for matcher, functions in plugin.webhook_listeners.items():
                self.webhook_listeners[matcher].extend(functions)

        print(self.webhook_listeners)

        self.webhook_queue = None

    def start(self, webhook_queue: Optional[Queue] = None):
        # If webhooks are enabled, we need to start a webhook queue listener
        if self.settings.WEBHOOK_HOST_ENABLED:
            self.webhook_queue = webhook_queue

            async def check_webhook_queue():
                logging.info("EventHandler WebHook queue listener started.")
                while True:
                    try:
                        webhook_id, data = self.webhook_queue.get_nowait()
                        await self._handle_webhook(webhook_id, data)
                    except Empty:
                        pass
                    await asyncio.sleep(0.0001)

            # Schedule the listener to the current event loop so that it starts together
            # with driver.init_websocket
            asyncio.get_event_loop().create_task(check_webhook_queue())

        # This is blocking, will loop forever
        self.driver.init_websocket(self.handle_event)

    def _should_ignore(self, message: Message):
        # Ignore message from senders specified in settings, and maybe from ourself
        return (
            True
            if message.sender_name.lower()
            in (name.lower() for name in self.settings.IGNORE_USERS)
            else False
        ) or (self.ignore_own_messages and message.sender_name == self.driver.username)

    async def handle_event(self, data):
        post = json.loads(data)
        event_action = post.get("event")
        if event_action == "posted":
            await self._handle_post(post)

    async def _handle_post(self, post):
        # For some reason these are JSON strings, so need to parse them first
        for item in ["post", "mentions"]:
            if post.get("data", {}).get(item):
                post["data"][item] = json.loads(post["data"][item])

        # If the post starts with a mention of this bot, strip off that part.
        post["data"]["post"]["message"] = self._name_matcher.sub(
            "", post["data"]["post"]["message"]
        )
        message = Message(post)
        if self._should_ignore(message):
            return

        # Find all the listeners that match this message, and have their plugins handle
        # the rest.
        tasks = []
        for matcher, functions in self.message_listeners.items():
            match = matcher.match(message.text)
            if match:
                groups = list([group for group in match.groups() if group != ""])
                for function in functions:
                    # Create an asyncio task to handle this callback
                    tasks.append(
                        asyncio.create_task(
                            function.plugin.call_function(
                                function, message, groups=groups
                            )
                        )
                    )
        # Execute the callbacks in parallel
        asyncio.gather(*tasks)

    async def _handle_webhook(self, webhook_id: str, data: Dict):
        if "trigger_id" in data:
            event = ActionEvent(data)
        else:
            event = WebHookEvent(data)

        # Find all the listeners that match this webhook id, and have their plugins
        # handle the rest.
        tasks = []
        for matcher, functions in self.webhook_listeners.items():
            match = matcher.match(webhook_id)
            if match:
                for function in functions:
                    # Create an asyncio task to handle this callback
                    tasks.append(
                        asyncio.create_task(
                            function.plugin.call_function(function, event)
                        )
                    )
        # Execute the callbacks in parallel
        asyncio.gather(*tasks)
