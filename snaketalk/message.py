from functools import cached_property
from typing import Dict


class Message(object):
    def __init__(
        self,
        body: Dict,
    ):
        self.body = body

    @cached_property
    def id(self):
        return self.body["data"]["post"]["id"]

    @cached_property
    def user_id(self):
        return self.body["data"]["post"]["user_id"]

    @cached_property
    def team_id(self):
        return self.body["data"].get("team_id", "").strip()

    @cached_property
    def text(self):
        return self.body["data"]["post"]["message"].strip()

    @cached_property
    def is_direct_message(self):
        return self.body["data"]["channel_type"] == "D"

    @cached_property
    def mentions(self):
        return self.body["data"].get("mentions", [])

    @cached_property
    def sender_name(self):
        return self.body["data"].get("sender_name", "").strip().strip("@")

    @cached_property
    def channel_id(self):
        return self.body["data"]["post"]["channel_id"]

    @cached_property
    def channel_name(self):
        return self.body["data"]["channel_name"]