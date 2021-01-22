import queue
import threading
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

import mattermostdriver

from snaketalk.message import Message


class ThreadPool(object):
    def __init__(self, num_workers: int):
        self.num_workers = num_workers
        self.alive = True
        self._queue = queue.Queue()
        self._busy_workers = queue.Queue()

        # Spawn num_workers threads that will wait for work to be added to the queue
        self._threads = []
        for _ in range(self.num_workers):
            worker = threading.Thread(target=self.handle_work)
            self._threads.append(worker)
            worker.start()

    def add_task(self, *args):
        self._queue.put(args)

    def get_busy_workers(self):
        return self._busy_workers.qsize()

    def stop(self):
        """Signals all threads that they should stop and waits for them to finish."""
        self.alive = False
        # Signal every thread that it's time to stop
        for _ in range(self.num_workers):
            self._queue.put((self._stop_thread, tuple()))
        # Wait for each of them to finish
        for thread in self._threads:
            thread.join()

    def _stop_thread(self):
        """Used to stop individual threads."""
        return

    def handle_work(self):
        while self.alive:
            # Wait for a new task (blocking)
            function, arguments = self._queue.get()
            # Notify the pool that we started working
            self._busy_workers.put(1)
            function(*arguments)
            # Notify the pool that we finished working
            self._queue.task_done()
            self._busy_workers.get()


class Driver(mattermostdriver.Driver):
    user_id: str = ""
    username: str = ""

    def __init__(self, *args, num_threads=10, **kwargs):
        super().__init__(*args, **kwargs)
        self.threadpool = ThreadPool(num_workers=num_threads)

    def login(self, *args, **kwargs):
        super().login(*args, **kwargs)
        self.user_id = self.client._userid
        self.username = self.client._username

    def create_post(
        self,
        channel_id: str,
        message: str,
        file_paths: Sequence[str] = [],
        root_id: str = "",
        props: Dict = {},
        ephemeral_user_id: Optional[str] = None,
    ):
        """Create a post in the specified channel with the specified text.

        Supports sending ephemeral messages if bot permissions allow it. If any file
        paths are specified, those files will be uploaded to mattermost first and then
        attached.
        """
        file_ids = (
            self.upload_files(file_paths, channel_id) if len(file_paths) > 0 else []
        )
        if ephemeral_user_id:
            return self.posts.create_ephemeral_post(
                {
                    "user_id": ephemeral_user_id,
                    "post": {
                        "channel_id": channel_id,
                        "message": message,
                        "file_ids": file_ids,
                        "root_id": root_id,
                        "props": props,
                    },
                }
            )

        return self.posts.create_post(
            {
                "channel_id": channel_id,
                "message": message,
                "file_ids": file_ids,
                "root_id": root_id,
                "props": props,
            }
        )

    def get_user_info(self, user_id: str):
        """Returns a dictionary of user info."""
        return self.users.get_user(user_id)

    def react_to(self, message: Message, emoji_name: str):
        """Adds an emoji reaction to the given message."""
        return self.reactions.create_reaction(
            {
                "user_id": self.user_id,
                "post_id": message.id,
                "emoji_name": emoji_name,
            },
        )

    def reply_to(
        self,
        message: Message,
        response: str,
        file_paths: Sequence[str] = [],
        props: Dict = {},
        ephemeral: bool = False,
    ):
        """Reply to the given message.

        Supports sending ephemeral messages if the bot permissions allow it. If the
        message is part of a thread, the reply will be added to that thread.
        """
        if ephemeral:
            return self.create_post(
                channel_id=message.channel_id,
                message=response,
                root_id=message.reply_id,
                file_paths=file_paths,
                props=props,
                ephemeral_user_id=message.user_id,
            )

        return self.create_post(
            channel_id=message.channel_id,
            message=response,
            root_id=message.reply_id,
            file_paths=file_paths,
            props=props,
        )

    def upload_files(
        self, file_paths: Sequence[Union[str, Path]], channel_id: str
    ) -> List[str]:
        """Given a list of file paths and the channel id, uploads the corresponding
        files and returns a list their internal file IDs."""
        file_dict = {}
        for path in file_paths:
            path = Path(path)
            file_dict[path.name] = Path(path).read_bytes()

        result = self.files.upload_file(channel_id, file_dict)
        return list(info["id"] for info in result["file_infos"])
